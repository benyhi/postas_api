from rest_framework import serializers

from apps.tenants.models import TenantConfig


class TenantConfigSerializer(serializers.ModelSerializer):
    tenant_id = serializers.UUIDField(source="tenant.uuid", read_only=True)

    class Meta:
        model = TenantConfig
        fields = [
            "tenant_id",
            "notification_email",
            "cashbox_email_notifications_enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["tenant_id", "created_at", "updated_at"]
