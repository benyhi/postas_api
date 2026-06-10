from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiParameter

from apps.platform_billing.enforcement import check_and_consume_billing_usage
from apps.sales.models import Sale, SaleDetail
from apps.sales.serializers import SaleCreateSerializer, SaleReadSerializer
from core.permissions.roles import IsAdminOrOwner
from core.utils.audit import log_action


@extend_schema_view(
    list=extend_schema(
        summary="Listar ventas",
        description=(
            "Lista paginada de ventas. ADMIN/OWNER ven todo el tenant; "
            "EMPLOYEE ve solo ventas de la caja abierta actual. "
            "Soporta filtros por user_id, payment_method, from y to."
        ),
        tags=["Sales"],
        parameters=[
            OpenApiParameter(name="user_id", description="Filtrar por UUID del usuario vendedor", type=str, required=False),
            OpenApiParameter(name="payment_method", description="Filtrar por metodo de pago (CASH, DEBIT, CREDIT, TRANSFER, QR)", type=str, required=False, enum=["CASH", "DEBIT", "CREDIT", "TRANSFER", "QR"]),
            OpenApiParameter(name="from", description="Fecha desde (YYYY-MM-DD)", type=str, required=False),
            OpenApiParameter(name="to", description="Fecha hasta (YYYY-MM-DD)", type=str, required=False),
        ],
    ),
)
class SaleListCreateView(generics.ListCreateAPIView):
    def get_serializer_class(self):
        if self.request.method == "POST":
            return SaleCreateSerializer
        return SaleReadSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Sale.objects.none()
        qs = Sale.objects.filter(tenant_id=self.request.tenant_id).select_related(
            "user", "cashbox",
        ).prefetch_related("details__product")

        if self.request.user.role == "EMPLOYEE":
            qs = qs.filter(cashbox__status="OPEN")

        # Filters
        user_id = self.request.query_params.get("user_id")
        if user_id:
            qs = qs.filter(user_id=user_id)

        payment_method = self.request.query_params.get("payment_method")
        if payment_method:
            qs = qs.filter(
                Q(payment_method=payment_method) |
                Q(payment_method="MIXED", payments__icontains=payment_method)
            )

        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        min_total = self.request.query_params.get("min_total")
        if min_total:
            qs = qs.filter(total__gte=min_total)

        max_total = self.request.query_params.get("max_total")
        if max_total:
            qs = qs.filter(total__lte=max_total)

        date_from = self.request.query_params.get("from")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        date_to = self.request.query_params.get("to")
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        return qs

    @extend_schema(
        summary="Registrar venta",
        description="Crea una nueva venta. Requiere una caja abierta. Valida stock y lo descuenta automaticamente.",
        tags=["Sales"],
        request=SaleCreateSerializer,
        responses={201: SaleReadSerializer},
        examples=[
            OpenApiExample(
                "Crear venta",
                value={"payment_method": "CASH", "items": [{"product_id": "uuid-del-producto", "quantity": "2.000"}]},
                request_only=True,
            ),
        ],
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            sale = serializer.save()
            check_and_consume_billing_usage(
                request.tenant_id,
                "pos_sales",
                amount=1,
                external_id=sale.uuid,
                idempotency_key=f"sale:{sale.uuid}",
                occurred_at=sale.created_at,
                metadata={
                    "sale": str(sale.uuid),
                    "total": str(sale.total),
                    "payment_method": sale.payment_method,
                    "items_count": sale.details.count(),
                },
                context={"source": "sales", "operation": "create_sale"},
            )
            log_action(request, "SALE", "SALE", sale.uuid, {
                "total": str(sale.total),
                "payment_method": sale.payment_method,
                "items_count": sale.details.count(),
            })
        read_serializer = SaleReadSerializer(sale)
        return Response(read_serializer.data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    retrieve=extend_schema(
        summary="Detalle de venta",
        description=(
            "Devuelve el detalle completo de una venta incluyendo sus items. "
            "EMPLOYEE solo puede ver ventas de la caja abierta actual."
        ),
        tags=["Sales"],
    ),
)
class SaleDetailView(generics.RetrieveAPIView):
    serializer_class = SaleReadSerializer
    lookup_field = "uuid"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Sale.objects.none()
        qs = Sale.objects.filter(
            tenant_id=self.request.tenant_id,
        ).select_related("user", "cashbox").prefetch_related("details__product")
        if self.request.user.role == "EMPLOYEE":
            qs = qs.filter(cashbox__status="OPEN")
        return qs


class SaleCancelView(APIView):
    permission_classes = [IsAdminOrOwner]

    @extend_schema(
        summary="Cancelar venta",
        description="Cancela una venta y revierte el stock de los productos. Solo ADMIN u OWNER.",
        tags=["Sales"],
        request=None,
        responses={200: SaleReadSerializer},
    )
    @transaction.atomic
    def post(self, request, uuid):
        try:
            sale = Sale.objects.select_for_update().get(
                uuid=uuid, tenant_id=request.tenant_id,
            )
        except Sale.DoesNotExist:
            return Response(
                {"detail": "Sale not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if sale.status == Sale.Status.CANCELLED:
            return Response(
                {"detail": "Sale is already cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Revert stock
        for detail in sale.details.select_related("product"):
            product = detail.product
            product.stock += detail.quantity
            product.save(update_fields=["stock"])

        sale.status = Sale.Status.CANCELLED
        sale.save(update_fields=["status"])

        log_action(request, "SALE", "SALE", sale.uuid, {
            "action": "CANCEL", "total": str(sale.total),
        })

        return Response(SaleReadSerializer(sale).data)
