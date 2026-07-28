from decimal import Decimal

from rest_framework import serializers


class ArcaItemSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=255)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=Decimal("0.0001"))
    final_unit_price = serializers.DecimalField(max_digits=15, decimal_places=2, min_value=Decimal("0.00"))


class ArcaReceiverSerializer(serializers.Serializer):
    doc_type = serializers.IntegerField(min_value=0, default=99)
    doc_number = serializers.RegexField(r"^\d+$", default="0", max_length=20)
    iva_condition_id = serializers.IntegerField(min_value=1, default=5)


class ArcaInvoiceCreateSerializer(serializers.Serializer):
    external_id = serializers.CharField(max_length=160)
    sale_id = serializers.UUIDField(required=False, allow_null=True)
    receiver = ArcaReceiverSerializer(required=False, default=dict)
    invoice_date = serializers.DateField(required=False)
    service_start_date = serializers.DateField(required=False, allow_null=True)
    service_end_date = serializers.DateField(required=False, allow_null=True)
    payment_due_date = serializers.DateField(required=False, allow_null=True)
    items = ArcaItemSerializer(many=True, min_length=1)

    def validate(self, attrs):
        supplied = [attrs.get("service_start_date"), attrs.get("service_end_date"), attrs.get("payment_due_date")]
        if any(supplied) and not all(supplied):
            raise serializers.ValidationError("Las fechas de servicio y vencimiento deben informarse juntas.")
        return attrs


class ArcaExplicitInvoiceCreateSerializer(ArcaInvoiceCreateSerializer):
    voucher_number = serializers.IntegerField(min_value=1)


class ArcaConfigurationWriteSerializer(serializers.Serializer):
    automatic_invoicing_enabled = serializers.BooleanField(required=False)
    arca_environment = serializers.ChoiceField(choices=["development", "production"], required=False)
    arca_cuit = serializers.RegexField(r"^\d{11}$", required=False)
    certificate = serializers.CharField(write_only=True, required=False, trim_whitespace=False)
    private_key = serializers.CharField(write_only=True, required=False, trim_whitespace=False)
    access_token = serializers.CharField(write_only=True, required=False, trim_whitespace=False)
    point_of_sale = serializers.IntegerField(min_value=1, required=False)
    automatic_voucher_type = serializers.IntegerField(min_value=1, required=False)
    concept = serializers.IntegerField(min_value=1, max_value=3, required=False)
    default_vat_rate = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100, required=False)
    default_vat_id = serializers.IntegerField(min_value=1, required=False)

    def validate(self, attrs):
        secret_fields = {"certificate", "private_key", "access_token"}
        fiscal_fields = {
            "arca_cuit",
            "certificate",
            "private_key",
            "access_token",
            "point_of_sale",
            "automatic_voucher_type",
        }
        if secret_fields.intersection(attrs) or fiscal_fields.intersection(attrs):
            missing = sorted(fiscal_fields - attrs.keys())
            if missing:
                raise serializers.ValidationError(
                    {field: "Este campo es obligatorio al configurar credenciales." for field in missing}
                )
        return attrs


class FiscalReferenceSerializer(serializers.Serializer):
    environment = serializers.ChoiceField(choices=["development", "production"])
    point_of_sale = serializers.IntegerField(min_value=1)
    voucher_type = serializers.IntegerField(min_value=1)
    voucher_number = serializers.IntegerField(min_value=1)


class ArcaInvoiceErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    retryable = serializers.BooleanField(required=False)


class ArcaInvoiceResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    tenant_id = serializers.UUIDField()
    environment = serializers.ChoiceField(choices=["development", "production"])
    fiscal_profile_id = serializers.IntegerField()
    sale_id = serializers.UUIDField(allow_null=True)
    external_id = serializers.CharField()
    actor_id = serializers.UUIDField(allow_null=True)
    actor_role = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    point_of_sale = serializers.IntegerField()
    voucher_type = serializers.IntegerField()
    voucher_number = serializers.IntegerField(allow_null=True)
    net_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    iva_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    cae = serializers.CharField(allow_null=True)
    cae_expiration_date = serializers.DateField(allow_null=True)
    observations = serializers.ListField(child=serializers.CharField())
    attempt_count = serializers.IntegerField()
    next_retry_at = serializers.DateTimeField(allow_null=True)
    error = ArcaInvoiceErrorSerializer(allow_null=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()


class ArcaConfigurationResponseSerializer(serializers.Serializer):
    tenant_id = serializers.UUIDField()
    automatic_invoicing_enabled = serializers.BooleanField()
    arca_environment = serializers.ChoiceField(choices=["development", "production"])
    profile = serializers.DictField(allow_null=True)


class ArcaLastVoucherResponseSerializer(serializers.Serializer):
    environment = serializers.ChoiceField(choices=["development", "production"])
    point_of_sale = serializers.IntegerField()
    voucher_type = serializers.IntegerField()
    last_voucher_number = serializers.IntegerField()
