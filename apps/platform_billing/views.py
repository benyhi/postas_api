import logging

from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .client import PlatformBillingClient, PlatformBillingError
from .serializers import BillingErrorSerializer, TenantBillingStatusSerializer


logger = logging.getLogger(__name__)


class CurrentTenantBillingStatusView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Plan y consumos del tenant actual",
        description=(
            "Devuelve el plan actual, estado de suscripcion y consumos/limites "
            "de features del tenant autenticado. Es un endpoint solo lectura para "
            "el frontend y no modifica datos de billing."
        ),
        tags=["Billing"],
        responses={
            200: TenantBillingStatusSerializer,
            400: OpenApiResponse(BillingErrorSerializer, description="JWT sin tenant_id."),
            401: OpenApiResponse(BillingErrorSerializer, description="Token faltante o invalido."),
            404: OpenApiResponse(
                BillingErrorSerializer,
                description="El tenant no tiene suscripcion registrada en platform.",
            ),
            503: OpenApiResponse(
                BillingErrorSerializer,
                description="No se pudo consultar postas_platform_api.",
            ),
        },
        examples=[
            OpenApiExample(
                "Respuesta",
                value={
                    "tenant_id": "00000000-0000-0000-0000-000000000001",
                    "status": "active",
                    "subscription": {
                        "plan": "business_ai",
                        "plan_name": "Business AI",
                        "status": "active",
                        "current_period_start": "2026-06-01T00:00:00Z",
                        "current_period_end": "2026-07-01T00:00:00Z",
                    },
                    "features": {
                        "document_extraction": {
                            "enabled": True,
                            "limit": 100,
                            "used": 12,
                            "remaining": 88,
                            "reset_period": "monthly",
                        },
                        "products": {
                            "enabled": True,
                            "limit": 1000,
                            "used": None,
                            "remaining": None,
                            "reset_period": None,
                        },
                    },
                },
                response_only=True,
            )
        ],
    )
    def get(self, request):
        tenant_id = getattr(request, "tenant_id", None)
        if not tenant_id:
            return Response(
                {"detail": "tenant_id no esta presente en el token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            billing_status = PlatformBillingClient().get_tenant_status(tenant_id)
        except PlatformBillingError as exc:
            return Response(
                _platform_error_response(exc),
                status=_platform_error_status(exc),
            )

        return Response(billing_status)


def _platform_error_response(exc: PlatformBillingError) -> dict[str, str]:
    if _is_subscription_not_found(exc):
        return {"detail": "subscription_not_found", "code": "subscription_not_found"}

    logger.warning(
        "Platform billing status lookup failed: status=%s detail=%s response=%s",
        exc.status_code,
        exc.message,
        exc.response_data,
    )
    return {
        "detail": "No se pudo consultar el estado de billing del tenant.",
        "code": "billing_service_unavailable",
    }


def _platform_error_status(exc: PlatformBillingError) -> int:
    if _is_subscription_not_found(exc):
        return status.HTTP_404_NOT_FOUND
    return status.HTTP_503_SERVICE_UNAVAILABLE


def _is_subscription_not_found(exc: PlatformBillingError) -> bool:
    if exc.status_code != status.HTTP_404_NOT_FOUND:
        return False
    code = (
        exc.response_data.get("code")
        or exc.response_data.get("reason")
        or exc.response_data.get("detail")
        or exc.message
    )
    return str(code) == "subscription_not_found"
