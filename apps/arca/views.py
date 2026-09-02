from __future__ import annotations

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.arca.client import PlatformArcaClient
from apps.arca.models import FiscalOutboxRequest
from apps.arca.serializers import (
    ArcaConfigurationWriteSerializer,
    ArcaExplicitInvoiceCreateSerializer,
    ArcaInvoiceCreateSerializer,
    ArcaInvoiceListQuerySerializer,
    ArcaInvoicePageSerializer,
    ArcaInvoiceResponseSerializer,
    ArcaSalesPointDiscoverySerializer,
    ArcaSalesPointListSerializer,
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


def _page_link(request, page):
    if page is None:
        return None
    query = request.query_params.copy()
    query["page"] = page
    return request.build_absolute_uri(f"{request.path}?{query.urlencode()}")


def _invoice_payload(sale, user, receiver, *, voucher_number=None):
    payload = {
        "external_id": str(sale.uuid),
        "sale_id": str(sale.uuid),
        "actor_id": str(user.uuid),
        "actor_role": user.role,
        "receiver": receiver,
        "invoice_date": sale.created_at.date().isoformat(),
        "items": [
            {
                "description": detail.product.name,
                "quantity": str(detail.quantity),
                "final_unit_price": str(detail.price),
            }
            for detail in sale.details.all()
        ],
    }
    if voucher_number is not None:
        payload["voucher_number"] = voucher_number
    return payload


def _sync_fiscal_tracking(*, sale, user, environment, payload, result, replace_payload):
    existing = FiscalOutboxRequest.objects.filter(sale=sale).first()
    external_id = str(result.get("external_id") or payload.get("external_id") or sale.uuid)
    FiscalOutboxRequest.objects.update_or_create(
        sale=sale,
        defaults={
            "tenant_id": sale.tenant_id,
            "created_by": user,
            "environment": environment,
            "external_id": external_id,
            "payload_snapshot": payload if replace_payload or existing is None else existing.payload_snapshot,
            "status": FiscalOutboxRequest.Status.SENT,
            "invoice_status": str(result.get("status") or "pending"),
            "platform_invoice_id": result.get("id"),
            "next_attempt_at": None,
            "locked_at": None,
            "last_error_code": "",
            "last_error_message": "",
        },
    )


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


class ArcaSalesPointDiscoveryView(APIView):
    permission_classes = [IsOwner]

    @extend_schema(
        request=ArcaSalesPointDiscoverySerializer,
        responses={200: ArcaSalesPointListSerializer},
    )
    def post(self, request):
        serializer = ArcaSalesPointDiscoverySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = PlatformArcaClient().discover_sales_points(
                request.tenant_id,
                dict(serializer.validated_data),
            )
        except PlatformBillingError as exc:
            return _platform_error(exc)
        return Response(result)


class ArcaInvoiceCreateView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ArcaInvoiceCreateSerializer
    explicit = False

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAdminOrOwner()]
        return super().get_permissions()

    @extend_schema(
        parameters=[ArcaInvoiceListQuerySerializer],
        responses={200: ArcaInvoicePageSerializer},
    )
    def get(self, request):
        serializer = ArcaInvoiceListQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        page = serializer.validated_data["page"]
        page_size = serializer.validated_data["page_size"]
        try:
            result = PlatformArcaClient().list_invoices(
                request.tenant_id,
                offset=(page - 1) * page_size,
                limit=page_size,
            )
        except PlatformBillingError as exc:
            return _platform_error(exc)
        count = int(result.get("count") or 0)
        return Response(
            {
                "count": count,
                "next": _page_link(request, page + 1) if page * page_size < count else None,
                "previous": _page_link(request, page - 1) if page > 1 else None,
                "results": result.get("results") or [],
            }
        )

    @extend_schema(responses={202: ArcaInvoiceResponseSerializer})
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                sale = (
                    Sale.objects.select_for_update()
                    .filter(
                        uuid=serializer.validated_data["sale_id"],
                        tenant_id=request.tenant_id,
                    )
                    .select_related("user")
                    .prefetch_related("details__product")
                    .first()
                )
                if sale is None:
                    return Response(
                        {"code": "sale_not_found", "message": "La venta no pertenece al tenant."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                if sale.status != Sale.Status.COMPLETED:
                    return Response(
                        {"code": "sale_not_completed", "message": "Solo se pueden facturar ventas completadas."},
                        status=status.HTTP_409_CONFLICT,
                    )
                if request.user.role == "EMPLOYEE" and sale.user_id != request.user.uuid:
                    return Response(
                        {"code": "sale_forbidden", "message": "El empleado solo puede facturar ventas propias."},
                        status=status.HTTP_403_FORBIDDEN,
                    )

                payload = _invoice_payload(
                    sale,
                    request.user,
                    serializer.validated_data["receiver"],
                    voucher_number=serializer.validated_data.get("voucher_number"),
                )
                config = _config_for(request.tenant_id)
                client = PlatformArcaClient()
                try:
                    existing = client.get_by_sale(request.tenant_id, sale.uuid)
                except PlatformBillingError as exc:
                    if exc.status_code != 404:
                        raise
                    existing = None

                tracking = FiscalOutboxRequest.objects.select_for_update().filter(sale=sale).first()
                queued_statuses = {
                    FiscalOutboxRequest.Status.PENDING,
                    FiscalOutboxRequest.Status.RETRYING,
                }
                if tracking is not None and (
                    tracking.status == FiscalOutboxRequest.Status.SENDING
                    or (existing is None and tracking.status in queued_statuses)
                ):
                    return Response(
                        {
                            "code": "automatic_invoice_pending",
                            "message": "La solicitud automatica pendiente no puede reemplazarse manualmente.",
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

                if existing is not None and existing.get("external_id"):
                    payload["external_id"] = str(existing["external_id"])

                canonical_existing = (
                    existing is not None and str(existing.get("external_id") or "") == str(sale.uuid)
                )
                if canonical_existing and existing.get("actor_id"):
                    payload["actor_id"] = str(existing["actor_id"])
                    payload["actor_role"] = existing.get("actor_role")
                tracked_payload = tracking.payload_snapshot if tracking is not None else None
                same_editable_data = tracked_payload is not None and (
                    tracked_payload.get("receiver") == payload.get("receiver")
                    and tracked_payload.get("voucher_number") == payload.get("voucher_number")
                )
                resume_receiver = (
                    self.explicit
                    and existing is not None
                    and existing.get("status") == "receiver_identification_required"
                )
                validate_canonical_retry = canonical_existing and not same_editable_data

                if existing is not None and not (resume_receiver or validate_canonical_retry):
                    result = existing
                    submitted_to_platform = False
                else:
                    result = client.create_invoice(
                        request.tenant_id,
                        config.arca_environment,
                        payload,
                        explicit=self.explicit,
                    )
                    submitted_to_platform = True
                _sync_fiscal_tracking(
                    sale=sale,
                    user=request.user,
                    environment=config.arca_environment,
                    payload=payload,
                    result=result,
                    replace_payload=submitted_to_platform,
                )
        except PlatformBillingError as exc:
            return _platform_error(exc)
        return Response(result, status=status.HTTP_202_ACCEPTED)


class ArcaExplicitInvoiceCreateView(ArcaInvoiceCreateView):
    http_method_names = ["post", "options"]
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
