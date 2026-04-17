from rest_framework import serializers

from apps.products.models import Category, Product


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = [
            "uuid", "tenant_id", "name", "active",
            "created_at", "updated_at",
        ]
        read_only_fields = ["uuid", "tenant_id", "created_at", "updated_at"]

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["tenant_id"] = request.tenant_id
        return super().create(validated_data)


class ProductSerializer(serializers.ModelSerializer):
    category_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    category = CategorySerializer(read_only=True)
    current_suppliers = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "uuid", "tenant_id", "name", "description",
            "price", "cost", "unit", "stock", "min_stock",
            "barcode", "category", "category_id", "active",
            "current_suppliers", "created_at", "updated_at",
        ]

    def get_current_suppliers(self, obj):
        return [
            {"uuid": str(s.uuid), "name": s.name}
            for s in obj.current_suppliers
        ]
        read_only_fields = ["uuid", "tenant_id", "created_at", "updated_at"]

    def validate_category_id(self, value):
        if value is None:
            return value
        request = self.context["request"]
        if not Category.objects.filter(uuid=value, tenant_id=request.tenant_id).exists():
            raise serializers.ValidationError("Category not found for this tenant.")
        return value

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["tenant_id"] = request.tenant_id
        category_id = validated_data.pop("category_id", None)
        if category_id:
            validated_data["category_id"] = category_id
        return super().create(validated_data)

    def update(self, instance, validated_data):
        category_id = validated_data.pop("category_id", None)
        if category_id is not None:
            validated_data["category_id"] = category_id
        return super().update(instance, validated_data)
