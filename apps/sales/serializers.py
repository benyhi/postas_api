from decimal import Decimal

from rest_framework import serializers
from django.db import transaction

from apps.sales.models import Sale, SaleDetail
from apps.products.models import Product
from apps.cashbox.models import Cashbox


class SaleDetailWriteSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))


class SaleCreateSerializer(serializers.Serializer):
    payment_method = serializers.ChoiceField(choices=Sale.PaymentMethod.choices)
    items = SaleDetailWriteSerializer(many=True, min_length=1)

    def validate(self, attrs):
        request = self.context["request"]
        tenant_id = request.tenant_id

        # Validate open cashbox
        cashbox = Cashbox.objects.filter(
            tenant_id=tenant_id, status=Cashbox.Status.OPEN,
        ).first()
        if not cashbox:
            raise serializers.ValidationError("No open cashbox. Open a cashbox first.")
        attrs["cashbox"] = cashbox

        # Validate products exist and have enough stock
        items = attrs["items"]
        product_ids = [item["product_id"] for item in items]
        products = Product.objects.filter(
            uuid__in=product_ids, tenant_id=tenant_id,
        )
        product_map = {p.uuid: p for p in products}

        for item in items:
            product = product_map.get(item["product_id"])
            if not product:
                raise serializers.ValidationError(
                    f"Product {item['product_id']} not found."
                )
            if product.stock < item["quantity"]:
                raise serializers.ValidationError(
                    f"Insufficient stock for {product.name}. "
                    f"Available: {product.stock}, requested: {item['quantity']}."
                )
            item["product"] = product

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        items = validated_data["items"]
        cashbox = validated_data["cashbox"]

        total = Decimal("0")
        details = []

        for item in items:
            product = item["product"]
            price = product.price  # snapshot
            quantity = item["quantity"]
            subtotal = price * quantity
            total += subtotal

            details.append(SaleDetail(
                product=product,
                quantity=quantity,
                price=price,
                subtotal=subtotal,
            ))

            # Decrement stock
            product.stock -= quantity
            product.save(update_fields=["stock"])

        sale = Sale.objects.create(
            tenant_id=request.tenant_id,
            user=request.user,
            cashbox=cashbox,
            total=total,
            payment_method=validated_data["payment_method"],
        )

        for detail in details:
            detail.sale = sale
        SaleDetail.objects.bulk_create(details)

        return sale


class SaleDetailReadSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = SaleDetail
        fields = ["uuid", "product", "product_name", "quantity", "price", "subtotal"]


class SaleReadSerializer(serializers.ModelSerializer):
    details = SaleDetailReadSerializer(many=True, read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Sale
        fields = [
            "uuid", "tenant_id", "user", "user_username",
            "cashbox", "total", "payment_method", "status",
            "created_at", "details",
        ]
