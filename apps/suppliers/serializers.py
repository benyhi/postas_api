from rest_framework import serializers

from apps.suppliers.models import Supplier, ProductSupplier


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = [
            "uuid", "tenant_id", "name", "phone", "email",
            "address", "notes", "active", "created_at", "updated_at",
        ]
        read_only_fields = ["uuid", "tenant_id", "created_at", "updated_at"]

    def create(self, validated_data):
        validated_data["tenant_id"] = self.context["request"].tenant_id
        return super().create(validated_data)


class ProductSupplierSerializer(serializers.ModelSerializer):
    supplier = SupplierSerializer(read_only=True)
    supplier_uuid = serializers.UUIDField(write_only=True)
    product_uuid = serializers.UUIDField(write_only=True)

    class Meta:
        model = ProductSupplier
        fields = [
            "uuid", "product_uuid", "supplier", "supplier_uuid",
            "price", "is_current", "since", "until",
        ]
        read_only_fields = ["uuid", "since", "until"]

    def validate(self, attrs):
        request = self.context["request"]
        product_uuid = attrs.get("product_uuid")
        supplier_uuid = attrs.get("supplier_uuid")

        from apps.products.models import Product
        if not Product.objects.filter(uuid=product_uuid, tenant_id=request.tenant_id).exists():
            raise serializers.ValidationError({"product_uuid": "Product not found for this tenant."})

        if not Supplier.objects.filter(uuid=supplier_uuid, tenant_id=request.tenant_id).exists():
            raise serializers.ValidationError({"supplier_uuid": "Supplier not found for this tenant."})

        return attrs

    def create(self, validated_data):
        product_uuid = validated_data.pop("product_uuid")
        supplier_uuid = validated_data.pop("supplier_uuid")

        from apps.products.models import Product
        validated_data["product_id"] = product_uuid
        validated_data["supplier_id"] = supplier_uuid
        return super().create(validated_data)


class SwitchSupplierSerializer(serializers.Serializer):
    product_uuid = serializers.UUIDField()
    supplier_uuid = serializers.UUIDField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True)

    def validate(self, attrs):
        request = self.context["request"]

        from apps.products.models import Product
        if not Product.objects.filter(uuid=attrs["product_uuid"], tenant_id=request.tenant_id).exists():
            raise serializers.ValidationError({"product_uuid": "Product not found for this tenant."})

        if not Supplier.objects.filter(uuid=attrs["supplier_uuid"], tenant_id=request.tenant_id).exists():
            raise serializers.ValidationError({"supplier_uuid": "Supplier not found for this tenant."})

        return attrs
