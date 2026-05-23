import json

from rest_framework import serializers

from .models import DocumentExtraction


class DocumentExtractionCreateSerializer(serializers.Serializer):
    image = serializers.FileField()
    provider = serializers.CharField(required=False, allow_blank=True, max_length=80)
    metadata = serializers.JSONField(required=False)

    def validate_metadata(self, value):
        if value in (None, ""):
            return {}
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError("metadata debe ser JSON valido.") from exc
            if not isinstance(parsed, dict):
                raise serializers.ValidationError("metadata debe ser un objeto JSON.")
            return parsed
        if not isinstance(value, dict):
            raise serializers.ValidationError("metadata debe ser un objeto JSON.")
        return value


class DocumentExtractionResultSerializer(serializers.ModelSerializer):
    confidence = serializers.SerializerMethodField()
    products = serializers.SerializerMethodField()

    class Meta:
        model = DocumentExtraction
        fields = ["uuid", "status", "confidence", "products", "error_message"]

    def get_confidence(self, obj):
        if obj.confidence is None:
            return None
        return float(obj.confidence)

    def get_products(self, obj):
        data = obj.extracted_data or {}
        products = data.get("products") if isinstance(data, dict) else None
        return products if isinstance(products, list) else []
