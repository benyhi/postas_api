from rest_framework import serializers


class TenantBillingSubscriptionSerializer(serializers.Serializer):
    plan = serializers.CharField()
    plan_name = serializers.CharField()
    status = serializers.CharField()
    current_period_start = serializers.DateTimeField()
    current_period_end = serializers.DateTimeField()


class TenantBillingStatusSerializer(serializers.Serializer):
    tenant_id = serializers.UUIDField()
    status = serializers.CharField()
    subscription = TenantBillingSubscriptionSerializer()
    features = serializers.DictField(
        child=serializers.JSONField(),
        help_text=(
            "Mapa feature_key -> {enabled, limit, used, remaining, reset_period}. "
            "Puede incluir campos adicionales devueltos por postas_platform_api."
        ),
    )


class BillingErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
    code = serializers.CharField(required=False)


class BillingEnforcementErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
    code = serializers.CharField()
    feature_key = serializers.CharField()
    limit = serializers.IntegerField(allow_null=True)
    used = serializers.IntegerField(allow_null=True)
    remaining = serializers.IntegerField(allow_null=True)
    upgrade_required = serializers.BooleanField()
