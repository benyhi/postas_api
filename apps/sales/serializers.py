from decimal import Decimal

from rest_framework import serializers
from django.db import transaction

from apps.sales.models import Sale, SaleDetail
from apps.products.models import Product
from apps.cashbox.models import Cashbox
from apps.arca.outbox import create_sale_fiscal_request
from apps.arca.models import FiscalOutboxRequest


class SaleDetailWriteSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal("0.001"))


class PaymentItemSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=Sale.PaymentMethod.choices)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))


class SaleCreateSerializer(serializers.Serializer):
    payments = PaymentItemSerializer(many=True, min_length=1, max_length=2)
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

        # Validate products, stock, and compute total
        items = attrs["items"]
        product_ids = [item["product_id"] for item in items]
        products = Product.objects.filter(uuid__in=product_ids, tenant_id=tenant_id)
        product_map = {p.uuid: p for p in products}

        computed_total = Decimal("0")
        for item in items:
            product = product_map.get(item["product_id"])
            if not product:
                raise serializers.ValidationError(f"Product {item['product_id']} not found.")
            if product.stock < item["quantity"]:
                raise serializers.ValidationError(
                    f"Insufficient stock for {product.name}. "
                    f"Available: {product.stock}, requested: {item['quantity']}."
                )
            item["product"] = product
            computed_total += product.price * item["quantity"]

        # Validate no duplicate payment methods
        payments = attrs["payments"]
        methods = [p["method"] for p in payments]
        if len(methods) != len(set(methods)):
            raise serializers.ValidationError("No se pueden repetir métodos de pago.")

        # Validate payments cover the total
        payments_total = sum(p["amount"] for p in payments)
        if payments_total < computed_total:
            raise serializers.ValidationError(
                f"El monto pagado ({payments_total}) es insuficiente para cubrir el total ({computed_total})."
            )

        attrs["computed_total"] = computed_total
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        items = validated_data["items"]
        cashbox = validated_data["cashbox"]
        payments = validated_data["payments"]
        total = validated_data["computed_total"]

        details = []
        for item in items:
            product = item["product"]
            price = product.price
            quantity = item["quantity"]
            subtotal = price * quantity
            details.append(SaleDetail(
                product=product,
                quantity=quantity,
                price=price,
                subtotal=subtotal,
            ))
            product.stock -= quantity
            product.save(update_fields=["stock"])

        primary_method = payments[0]["method"] if len(payments) == 1 else Sale.PaymentMethod.MIXED
        payments_data = [{"method": p["method"], "amount": str(p["amount"])} for p in payments]

        sale = Sale.objects.create(
            tenant_id=request.tenant_id,
            user=request.user,
            cashbox=cashbox,
            total=total,
            payment_method=primary_method,
            payments=payments_data,
        )

        for detail in details:
            detail.sale = sale
        SaleDetail.objects.bulk_create(details)

        create_sale_fiscal_request(sale, request.user)

        return sale


class SaleDetailReadSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = SaleDetail
        fields = ["uuid", "product", "product_name", "quantity", "price", "subtotal"]


class SaleReadSerializer(serializers.ModelSerializer):
    details = SaleDetailReadSerializer(many=True, read_only=True)
    user_username = serializers.CharField(source="user.username", read_only=True)
    invoice_status = serializers.SerializerMethodField()
    invoice_tracking_id = serializers.SerializerMethodField()

    def get_invoice_status(self, obj) -> str:
        try:
            return obj.fiscal_request.invoice_status
        except (AttributeError, FiscalOutboxRequest.DoesNotExist):
            return "not_requested"

    def get_invoice_tracking_id(self, obj) -> str | None:
        try:
            return obj.fiscal_request.external_id
        except (AttributeError, FiscalOutboxRequest.DoesNotExist):
            return None

    class Meta:
        model = Sale
        fields = [
            "uuid", "tenant_id", "user", "user_username",
            "cashbox", "total", "payment_method", "payments", "status",
            "created_at", "details", "invoice_status", "invoice_tracking_id",
        ]
