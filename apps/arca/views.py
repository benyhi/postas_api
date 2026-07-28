from __future__ import annotations

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.arca.client import PlatformArcaClient
from apps.arca.serializers import (
    ArcaConfigurationWriteSerializer,
    ArcaExplicitInvoiceCreateSerializer,
    ArcaInvoiceCreateSerializer,
    ArcaInvoiceResponseSerializer,
    ArcaConfigurationResponseSerializer,
    ArcaLastVoucherResponseSerializer,
    FiscalReferenceSerializer,
)
from apps.platform_billing.client import PlatformBillingError
from apps.sales.models import Sale
from apps.tenants.models import Tenant, TenantConfig
from core.permissions.roles import IsAdminOrOwner, IsOwner


def _platform_error(exc: PlatformBillingError):
    response_status = exc.status_code if 400 <= exc.status_code < 600 else 503
    data = exc.response_data.get("detail") if isinstance(exc.response_data, dict) else None
    if not isinstance(data, dict):
        data = {"code": "arca_platform_error", "message": exc.message}
    return Response(data, status=response_status)


def _config_for(tenant_id):
    tenant, _ = Tenant.objects.get_or_create(uuid=tenant_id)
    config, _ = TenantConfig.objects.get_or_create(tenant=tenant)
    return config


class ArcaConfigurationView(APIView):
    permission_classes = [IsOwner]

    @extend_schema(responses={200: ArcaConfigurationResponseSerializer})
    def get(self, request):
        config = _config_for(request.tenant_id)
        profile = None
        try:
            profile = PlatformArcaClient().get_profile(request.tenant_id, config.arca_environment)
        except PlatformBillingError as exc:
            if exc.status_code != 404:
                return _platform_error(exc)
        return Response(
            {
                "tenant_id": str(request.tenant_id),
                "automatic_invoicing_enabled": config.automatic_invoicing_enabled,
                "arca_environment": config.arca_environment,
                "profile": profile,
            }
        )

    @extend_schema(
        request=ArcaConfigurationWriteSerializer,
        responses={200: ArcaConfigurationResponseSerializer},
    )
    def put(self, request):
        serializer = ArcaConfigurationWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        config = _config_for(request.tenant_id)
        environment = data.get("arca_environment", config.arca_environment)
        client = PlatformArcaClient()

        profile_fields = {
            "arca_cuit",
            "certificate",
            "private_key",
            "access_token",
            "point_of_sale",
            "automatic_voucher_type",
            "concept",
            "default_vat_rate",
            "default_vat_id",
        }
        profile = None
        if profile_fields.intersection(data):
            profile_payload = {key: data[key] for key in profile_fields if key in data}
            profile_payload.setdefault("concept", 1)
            profile_payload.setdefault("default_vat_rate", "21.00")
            profile_payload.setdefault("default_vat_id", 5)
            try:
                client.check_entitlement(request.tenant_id, "arca_invoicing")
                profile = client.put_profile(request.tenant_id, environment, profile_payload)
                validation = client.validate_profile(request.tenant_id, environment)
            except PlatformBillingError as exc:
                return _platform_error(exc)
            if validation.get("valid") is not True:
                return Response(
                    {"code": "fiscal_profile_invalid", "message": validation.get("error") or "No se pudo validar el perfil fiscal."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            profile["validation_status"] = "valid"

        enabling = data.get("automatic_invoicing_enabled", config.automatic_invoicing_enabled)
        if enabling:
            try:
                entitlement = client.check_entitlement(request.tenant_id, "arca_invoicing")
                if entitlement.get("allowed") is not True:
                    return Response(
                        {"code": entitlement.get("reason", "feature_not_enabled"), "message": entitlement.get("message", "El plan no habilita ARCA.")},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                profile = profile or client.get_profile(request.tenant_id, environment)
            except PlatformBillingError as exc:
                return _platform_error(exc)
            if profile.get("validation_status") != "valid":
                return Response(
                    {"code": "fiscal_profile_not_valid", "message": "El perfil fiscal debe estar validado para activar la automatizacion."},
                    status=status.HTTP_409_CONFLICT,
                )
            if int(profile.get("concept") or 0) != 1:
                return Response(
                    {
                        "code": "automatic_invoicing_requires_products_concept",
                        "message": "La facturacion automatica de ventas requiere un perfil con concepto productos.",
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        with transaction.atomic():
            config.arca_environment = environment
            config.automatic_invoicing_enabled = enabling
            config.save(update_fields=["arca_environment", "automatic_invoicing_enabled", "updated_at"])
        return Response(
            {
                "tenant_id": str(request.tenant_id),
                "automatic_invoicing_enabled": config.automatic_invoicing_enabled,
                "arca_environment": config.arca_environment,
                "profile": profile,
            }
        )

    @extend_schema(request=None, responses={204: None})
    def delete(self, request):
        config = _config_for(request.tenant_id)
        try:
            PlatformArcaClient().delete_profile(request.tenant_id, config.arca_environment)
        except PlatformBillingError as exc:
            if exc.status_code != 404:
                return _platform_error(exc)
        config.automatic_invoicing_enabled = False
        config.save(update_fields=["automatic_invoicing_enabled", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class ArcaInvoiceCreateView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ArcaInvoiceCreateSerializer
    explicit = False

    @extend_schema(responses={202: ArcaInvoiceResponseSerializer})
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        sale_id = payload.get("sale_id")
        if sale_id and not Sale.objects.filter(uuid=sale_id, tenant_id=request.tenant_id).exists():
            return Response({"code": "sale_not_found", "message": "La venta no pertenece al tenant."}, status=404)
        payload["actor_id"] = str(request.user.uuid)
        payload["actor_role"] = request.user.role
        config = _config_for(request.tenant_id)
        try:
            result = PlatformArcaClient().create_invoice(
                request.tenant_id,
                config.arca_environment,
                payload,
                explicit=self.explicit,
            )
        except PlatformBillingError as exc:
            return _platform_error(exc)
        return Response(result, status=status.HTTP_202_ACCEPTED)


class ArcaExplicitInvoiceCreateView(ArcaInvoiceCreateView):
    serializer_class = ArcaExplicitInvoiceCreateSerializer
    explicit = True


class ArcaInvoiceByExternalIdView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ArcaInvoiceResponseSerializer})
    def get(self, request, external_id):
        try:
            result = PlatformArcaClient().get_by_external_id(request.tenant_id, external_id)
        except PlatformBillingError as exc:
            return _platform_error(exc)
        actor_id = str(result.get("actor_id") or "")
        if request.user.role not in {"ADMIN", "OWNER"} and actor_id != str(request.user.uuid):
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(result)


class ArcaFiscalReferenceView(APIView):
    permission_classes = [IsAdminOrOwner]

    @extend_schema(parameters=[FiscalReferenceSerializer], responses={200: ArcaInvoiceResponseSerializer})
    def get(self, request):
        serializer = FiscalReferenceSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        try:
            result = PlatformArcaClient().get_fiscal(request.tenant_id, **serializer.validated_data)
        except PlatformBillingError as exc:
            return _platform_error(exc)
        return Response(result)


class ArcaLastVoucherView(APIView):
    permission_classes = [IsAdminOrOwner]

    @extend_schema(responses={200: ArcaLastVoucherResponseSerializer})
    def get(self, request):
        config = _config_for(request.tenant_id)
        voucher_type = request.query_params.get("voucher_type")
        try:
            result = PlatformArcaClient().get_last_voucher(
                request.tenant_id,
                config.arca_environment,
                int(voucher_type) if voucher_type else None,
            )
        except (TypeError, ValueError):
            return Response({"voucher_type": "Debe ser un entero positivo."}, status=400)
        except PlatformBillingError as exc:
            return _platform_error(exc)
        return Response(result)
