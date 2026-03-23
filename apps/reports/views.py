from datetime import date

from django.db.models import Sum, Count, Avg, F
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample, inline_serializer

from apps.sales.models import Sale, SaleDetail
from apps.cashbox.models import Cashbox
from core.permissions.roles import IsAdminOrOwner

_date_params = [
    OpenApiParameter(name="from", description="Fecha desde (YYYY-MM-DD). Por defecto: hoy.", type=str, required=False),
    OpenApiParameter(name="to", description="Fecha hasta (YYYY-MM-DD)", type=str, required=False),
]


class DailySalesReportView(APIView):
    permission_classes = [IsAdminOrOwner]

    @extend_schema(
        summary="Reporte de ventas diarias",
        description="Retorna total vendido, cantidad de ventas y promedio. Filtra por rango de fechas (from/to). Sin fechas, muestra solo hoy.",
        tags=["Reports"],
        parameters=_date_params,
        responses={200: inline_serializer("DailySalesReport", fields={
            "total_sold": serializers.DecimalField(max_digits=12, decimal_places=2),
            "sale_count": serializers.IntegerField(),
            "average_sale": serializers.DecimalField(max_digits=12, decimal_places=2),
        })},
        examples=[
            OpenApiExample("Respuesta", value={"total_sold": 25000.00, "sale_count": 12, "average_sale": 2083.33}, response_only=True),
        ],
    )
    def get(self, request):
        qs = Sale.objects.filter(
            tenant_id=request.tenant_id,
            status=Sale.Status.COMPLETED,
        )

        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")

        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        else:
            qs = qs.filter(created_at__date=timezone.now().date())

        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        stats = qs.aggregate(
            total_sold=Sum("total"),
            sale_count=Count("uuid"),
            average_sale=Avg("total"),
        )

        return Response({
            "total_sold": stats["total_sold"] or 0,
            "sale_count": stats["sale_count"] or 0,
            "average_sale": round(stats["average_sale"] or 0, 2),
        })


class SalesByPaymentReportView(APIView):
    permission_classes = [IsAdminOrOwner]

    @extend_schema(
        summary="Ventas por metodo de pago",
        description="Desglose de ventas agrupadas por metodo de pago. Filtra por rango de fechas.",
        tags=["Reports"],
        parameters=_date_params,
        responses={200: inline_serializer("SalesByPaymentReport", fields={
            "payment_method": serializers.CharField(),
            "total": serializers.DecimalField(max_digits=12, decimal_places=2),
            "count": serializers.IntegerField(),
        }, many=True)},
        examples=[
            OpenApiExample("Respuesta", value=[{"payment_method": "CASH", "total": 15000.00, "count": 8}, {"payment_method": "DEBIT", "total": 10000.00, "count": 4}], response_only=True),
        ],
    )
    def get(self, request):
        qs = Sale.objects.filter(
            tenant_id=request.tenant_id,
            status=Sale.Status.COMPLETED,
        )

        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        breakdown = qs.values("payment_method").annotate(
            total=Sum("total"),
            count=Count("uuid"),
        ).order_by("payment_method")

        return Response(list(breakdown))


class TopProductsReportView(APIView):
    permission_classes = [IsAdminOrOwner]

    @extend_schema(
        summary="Productos mas vendidos",
        description="Top N productos por cantidad vendida. Filtra por rango de fechas y limite.",
        tags=["Reports"],
        parameters=_date_params + [
            OpenApiParameter(name="limit", description="Cantidad maxima de productos (default: 10)", type=int, required=False),
        ],
        responses={200: inline_serializer("TopProductsReport", fields={
            "product__uuid": serializers.UUIDField(),
            "product__name": serializers.CharField(),
            "total_quantity": serializers.DecimalField(max_digits=12, decimal_places=3),
            "total_revenue": serializers.DecimalField(max_digits=12, decimal_places=2),
        }, many=True)},
        examples=[
            OpenApiExample("Respuesta", value=[{"product__uuid": "uuid", "product__name": "Coca Cola 500ml", "total_quantity": 45.0, "total_revenue": 67500.0}], response_only=True),
        ],
    )
    def get(self, request):
        limit = int(request.query_params.get("limit", 10))

        qs = SaleDetail.objects.filter(
            sale__tenant_id=request.tenant_id,
            sale__status=Sale.Status.COMPLETED,
        )

        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")
        if date_from:
            qs = qs.filter(sale__created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(sale__created_at__date__lte=date_to)

        top = qs.values(
            "product__uuid", "product__name",
        ).annotate(
            total_quantity=Sum("quantity"),
            total_revenue=Sum("subtotal"),
        ).order_by("-total_quantity")[:limit]

        return Response(list(top))


class CashboxSummaryReportView(APIView):
    permission_classes = [IsAdminOrOwner]

    @extend_schema(
        summary="Resumen de caja",
        description="Resumen de una caja especifica o la caja abierta actual. Incluye desglose por metodo de pago.",
        tags=["Reports"],
        parameters=[
            OpenApiParameter(name="cashbox_id", description="UUID de la caja. Si no se envia, usa la caja abierta.", type=str, required=False),
        ],
        responses={200: inline_serializer("CashboxSummaryReport", fields={
            "cashbox_uuid": serializers.UUIDField(),
            "status": serializers.CharField(),
            "opened_at": serializers.DateTimeField(),
            "closed_at": serializers.DateTimeField(allow_null=True),
            "initial_amount": serializers.DecimalField(max_digits=12, decimal_places=2),
            "final_amount": serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True),
            "expected_amount": serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True),
            "difference": serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True),
            "total_sold": serializers.DecimalField(max_digits=12, decimal_places=2),
            "sale_count": serializers.IntegerField(),
            "by_payment_method": serializers.ListField(),
        })},
    )
    def get(self, request):
        cashbox_id = request.query_params.get("cashbox_id")

        if cashbox_id:
            try:
                cashbox = Cashbox.objects.get(
                    uuid=cashbox_id, tenant_id=request.tenant_id,
                )
            except Cashbox.DoesNotExist:
                return Response({"detail": "Cashbox not found."}, status=404)
        else:
            # Default: current open cashbox
            cashbox = Cashbox.objects.filter(
                tenant_id=request.tenant_id, status=Cashbox.Status.OPEN,
            ).first()
            if not cashbox:
                return Response({"detail": "No open cashbox."}, status=404)

        sales_qs = Sale.objects.filter(
            cashbox=cashbox, status=Sale.Status.COMPLETED,
        )
        stats = sales_qs.aggregate(
            total_sold=Sum("total"),
            sale_count=Count("uuid"),
        )

        by_payment = sales_qs.values("payment_method").annotate(
            total=Sum("total"), count=Count("uuid"),
        ).order_by("payment_method")

        return Response({
            "cashbox_uuid": cashbox.uuid,
            "status": cashbox.status,
            "opened_at": cashbox.opened_at,
            "closed_at": cashbox.closed_at,
            "initial_amount": cashbox.initial_amount,
            "final_amount": cashbox.final_amount,
            "expected_amount": cashbox.expected_amount,
            "difference": cashbox.difference,
            "total_sold": stats["total_sold"] or 0,
            "sale_count": stats["sale_count"] or 0,
            "by_payment_method": list(by_payment),
        })
