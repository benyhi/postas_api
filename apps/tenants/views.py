from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema

from apps.tenants.models import Tenant, TenantConfig
from apps.tenants.serializers import TenantConfigSerializer
from core.permissions.roles import IsOwner
from core.utils.audit import log_action


class TenantConfigView(APIView):
    permission_classes = [IsOwner]

    @extend_schema(
        summary="Obtener configuracion del tenant",
        description="Devuelve la configuracion del tenant actual. Solo OWNER.",
        tags=["TenantConfig"],
        responses={200: TenantConfigSerializer},
    )
    def get(self, request):
        config = self._get_or_create_config(request.tenant_id)
        return Response(TenantConfigSerializer(config).data)

    @extend_schema(
        summary="Actualizar configuracion del tenant",
        description="Actualiza la configuracion del tenant actual. Solo OWNER.",
        tags=["TenantConfig"],
        request=TenantConfigSerializer,
        responses={200: TenantConfigSerializer},
    )
    def patch(self, request):
        config = self._get_or_create_config(request.tenant_id)
        serializer = TenantConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        log_action(request, "UPDATE", "TENANT_CONFIG", config.tenant_id, {
            "notification_email": config.notification_email,
            "cashbox_email_notifications_enabled": config.cashbox_email_notifications_enabled,
        })

        return Response(serializer.data)

    put = patch

    @staticmethod
    def _get_or_create_config(tenant_id):
        tenant, _ = Tenant.objects.get_or_create(uuid=tenant_id)
        config, _ = TenantConfig.objects.get_or_create(tenant=tenant)
        return config
