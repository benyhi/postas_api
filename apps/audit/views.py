from rest_framework import generics
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter

from apps.audit.models import AuditLog
from apps.audit.serializers import AuditLogSerializer
from core.permissions.roles import IsAdminOrOwner


@extend_schema_view(
    list=extend_schema(
        summary="Listar logs de auditoria",
        description="Lista paginada de logs de auditoria. Soporta filtros por action, entity, user y rango de timestamp.",
        tags=["Audit"],
        parameters=[
            OpenApiParameter(name="action", description="Filtrar por tipo de accion (CREATE, UPDATE, DELETE, SALE, CASHBOX)", type=str, required=False),
            OpenApiParameter(name="entity", description="Filtrar por entidad (USER, PRODUCT, CATEGORY, SALE, CASHBOX)", type=str, required=False),
            OpenApiParameter(name="user", description="Filtrar por UUID del usuario", type=str, required=False),
            OpenApiParameter(name="timestamp__gte", description="Timestamp desde (ISO 8601)", type=str, required=False),
            OpenApiParameter(name="timestamp__lte", description="Timestamp hasta (ISO 8601)", type=str, required=False),
            OpenApiParameter(name="timestamp__date", description="Filtrar por fecha exacta (YYYY-MM-DD)", type=str, required=False),
        ],
    ),
)
class AuditLogListView(generics.ListAPIView):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminOrOwner]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = {
        "action": ["exact"],
        "entity": ["exact"],
        "user": ["exact"],
        "timestamp": ["gte", "lte", "date"],
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return AuditLog.objects.none()
        return AuditLog.objects.filter(
            tenant_id=self.request.tenant_id,
        ).select_related("user")
