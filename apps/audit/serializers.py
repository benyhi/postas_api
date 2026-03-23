from rest_framework import serializers

from apps.audit.models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source="user.username", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = [
            "uuid", "tenant_id", "user", "user_username",
            "action", "entity", "entity_id",
            "timestamp", "metadata",
        ]
