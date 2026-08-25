from rest_framework import serializers

from apps.cashbox.models import Cashbox, CashRegister


class CashRegisterSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashRegister
        fields = ["uuid", "name", "active", "created_at", "updated_at"]
        read_only_fields = ["uuid", "created_at", "updated_at"]

    def validate_name(self, value):
        request = self.context["request"]
        queryset = CashRegister.objects.filter(tenant_id=request.tenant_id, name=value)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("A cash register with this name already exists.")
        return value

    def validate(self, attrs):
        if self.instance is None and attrs.get("active") is False:
            raise serializers.ValidationError({"active": "A new cash register must be active."})
        if self.instance is not None and not self.instance.active and attrs.get("active") is True:
            raise serializers.ValidationError({"active": "An inactive cash register cannot be reactivated."})
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        return CashRegister.objects.create(tenant_id=request.tenant_id, **validated_data)


class CashboxOpenSerializer(serializers.ModelSerializer):
    register_id = serializers.PrimaryKeyRelatedField(
        queryset=CashRegister.objects.all(),
        source="register",
        write_only=True,
    )

    class Meta:
        model = Cashbox
        fields = ["register_id", "initial_amount"]

    def validate(self, attrs):
        request = self.context["request"]
        register = attrs["register"]
        if str(register.tenant_id) != str(request.tenant_id) or not register.active:
            raise serializers.ValidationError({"register_id": "Active cash register not found."})
        if Cashbox.objects.filter(
            tenant_id=request.tenant_id,
            opened_by=request.user,
            status=Cashbox.Status.OPEN,
        ).exists():
            raise serializers.ValidationError("The user already has an open cashbox.")
        if Cashbox.objects.filter(
            tenant_id=request.tenant_id,
            register=register,
            status=Cashbox.Status.OPEN,
        ).exists():
            raise serializers.ValidationError("The cash register already has an open cashbox.")
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
    cashbox_id = serializers.UUIDField(required=False, write_only=True)


class CashboxReadSerializer(serializers.ModelSerializer):
    register_name = serializers.CharField(
        source="register.name",
        read_only=True,
        default=None,
        allow_null=True,
    )
    opened_by_username = serializers.CharField(source="opened_by.username", read_only=True)
    closed_by_username = serializers.CharField(
        source="closed_by.username", read_only=True, default=None,
    )

    class Meta:
        model = Cashbox
        fields = [
            "uuid", "tenant_id", "register", "register_name",
            "opened_by", "opened_by_username",
            "closed_by", "closed_by_username",
            "opened_at", "closed_at",
            "initial_amount", "final_amount",
            "expected_amount", "difference", "status",
        ]
