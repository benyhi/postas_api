from rest_framework import serializers

from apps.cashbox.models import Cashbox


class CashboxOpenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cashbox
        fields = ["initial_amount"]

    def validate(self, attrs):
        request = self.context["request"]
        if Cashbox.objects.filter(tenant_id=request.tenant_id, status=Cashbox.Status.OPEN).exists():
            raise serializers.ValidationError("There is already an open cashbox for this tenant.")
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        return Cashbox.objects.create(
            tenant_id=request.tenant_id,
            opened_by=request.user,
            **validated_data,
        )


class CashboxCloseSerializer(serializers.Serializer):
    final_amount = serializers.DecimalField(max_digits=12, decimal_places=2)


class CashboxReadSerializer(serializers.ModelSerializer):
    opened_by_username = serializers.CharField(source="opened_by.username", read_only=True)
    closed_by_username = serializers.CharField(
        source="closed_by.username", read_only=True, default=None,
    )

    class Meta:
        model = Cashbox
        fields = [
            "uuid", "tenant_id", "opened_by", "opened_by_username",
            "closed_by", "closed_by_username",
            "opened_at", "closed_at",
            "initial_amount", "final_amount",
            "expected_amount", "difference", "status",
        ]
