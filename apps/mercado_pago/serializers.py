from rest_framework import serializers


class OAuthAuthorizationResponseSerializer(serializers.Serializer):
    authorization_url = serializers.URLField(read_only=True)
    expires_at = serializers.DateTimeField(read_only=True)


class ConnectionStatusSerializer(serializers.Serializer):
    tenant_id = serializers.UUIDField(read_only=True)
    connected = serializers.BooleanField(read_only=True)
    status = serializers.CharField(read_only=True)
    collector_id = serializers.CharField(read_only=True, allow_null=True)
    scopes = serializers.ListField(child=serializers.CharField(), read_only=True)
    live_mode = serializers.BooleanField(read_only=True, allow_null=True)
    application_id = serializers.CharField(read_only=True, allow_null=True)
    integration_id = serializers.CharField(read_only=True, allow_null=True)
    token_expires_at = serializers.DateTimeField(read_only=True, allow_null=True)


class ResourceDiscoverySerializer(serializers.Serializer):
    results = serializers.ListField(child=serializers.DictField(), read_only=True)


class WebhookReceiptSerializer(serializers.Serializer):
    received = serializers.BooleanField(read_only=True)


class MercadoPagoSaleStatusSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=("POINT", "QR"), read_only=True)
    state = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True, allow_null=True)
    status_detail = serializers.CharField(read_only=True, allow_null=True)
    qr_data = serializers.CharField(read_only=True, allow_null=True)
    expires_at = serializers.DateTimeField(read_only=True, allow_null=True)


class CashRegisterAssociationSerializer(serializers.Serializer):
    terminal_id = serializers.CharField(required=False, allow_blank=False, max_length=120)
    pos_id = serializers.CharField(required=False, allow_blank=False, max_length=120)
    external_pos_id = serializers.CharField(required=False, allow_blank=False, max_length=120)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("At least one Mercado Pago resource is required.")
        return attrs
