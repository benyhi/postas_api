from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiParameter

from apps.platform_billing.enforcement import check_and_consume_billing_usage
from apps.platform_billing.client import PlatformBillingError
from apps.mercado_pago.client import PlatformMercadoPagoClient
from apps.mercado_pago.models import MercadoPagoOrder
from apps.mercado_pago.services import (
    MercadoPagoConflict,
    create_external_sale,
    ensure_sale_replay_access,
    reconcile_order,
    request_fingerprint,
    stable_operation_key,
)
from apps.sales.models import Sale, SaleDetail
from apps.sales.serializers import SaleCreateSerializer, SaleReadSerializer
from apps.cashbox.models import Cashbox
from apps.tenants.models import Tenant
from core.permissions.roles import IsAdminOrOwner
from core.utils.audit import log_action


@extend_schema_view(
    get=extend_schema(
        summary="Listar ventas",
        description=(
            "Lista paginada de ventas. ADMIN/OWNER ven todo el tenant; "
            "EMPLOYEE ve solo ventas de la caja abierta actual. "
            "Soporta filtros por user_id, payment_method, from y to."
        ),
        tags=["Sales"],
        parameters=[
            OpenApiParameter(name="user_id", description="Filtrar por UUID del usuario vendedor", type=str, required=False),
            OpenApiParameter(name="cashbox_id", description="Filtrar por UUID de la sesion de caja", type=str, required=False),
            OpenApiParameter(name="register_id", description="Filtrar por UUID de la terminal", type=str, required=False),
            OpenApiParameter(
                name="payment_method",
                description="Filtrar por metodo de pago, incluyendo lineas de ventas mixtas",
                type=str,
                required=False,
                enum=["CASH", "CARD", "TRANSFER", "POINT", "QR", "MIXED"],
            ),
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
            "user", "cashbox", "cashbox__register", "mercado_pago_order",
        ).prefetch_related("details__product")

        if self.request.user.role == "EMPLOYEE":
            qs = qs.filter(cashbox__status="OPEN", cashbox__opened_by=self.request.user)

        # Filters
        user_id = self.request.query_params.get("user_id")
        if user_id:
            qs = qs.filter(user_id=_uuid_query_param(self.request, "user_id"))

        cashbox_id = self.request.query_params.get("cashbox_id")
        if cashbox_id:
            qs = qs.filter(cashbox_id=_uuid_query_param(self.request, "cashbox_id"))

        register_id = self.request.query_params.get("register_id")
        if register_id:
            qs = qs.filter(cashbox__register_id=_uuid_query_param(self.request, "register_id"))

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
        description=(
            "Crea una venta local (201) o POINT/QR pendiente (202). Las ventas externas "
            "requieren X-Idempotency-Key, reservan stock y se concilian en segundo plano."
        ),
        tags=["Sales"],
        request=SaleCreateSerializer,
        responses={201: SaleReadSerializer, 202: SaleReadSerializer},
        parameters=[
            OpenApiParameter(
                name="X-Idempotency-Key", location=OpenApiParameter.HEADER,
                type=str, required=False, description="Required for POINT/QR sales",
            ),
        ],
        examples=[
            OpenApiExample(
                "Crear venta local",
                value={
                    "payments": [{"method": "CASH", "amount": "3000.00"}],
                    "items": [{"product_id": "uuid-del-producto", "quantity": "2.000"}],
                },
                request_only=True,
            ),
        ],
    )
    def create(self, request, *args, **kwargs):
        idempotency_key = request.headers.get("X-Idempotency-Key", "").strip()
        has_external_payment = any(
            isinstance(payment, dict) and payment.get("method") in {
                Sale.PaymentMethod.POINT, Sale.PaymentMethod.QR,
            }
            for payment in (request.data.get("payments", []) if isinstance(request.data, dict) else [])
        )
        if has_external_payment and idempotency_key:
            existing = MercadoPagoOrder.objects.select_related(
                "sale__user", "sale__cashbox__register",
            ).filter(
                tenant_id=request.tenant_id,
                frontend_idempotency_key=idempotency_key,
            ).first()
            if existing:
                ensure_sale_replay_access(request, existing.sale)
                if existing.request_fingerprint != request_fingerprint(request.data):
                    return Response(
                        {"detail": "The idempotency key was already used with a different request.", "code": "idempotency_conflict"},
                        status=status.HTTP_409_CONFLICT,
                    )
                return Response(SaleReadSerializer(existing.sale).data, status=status.HTTP_202_ACCEPTED)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("external_payment"):
            try:
                sale, replay = create_external_sale(
                    request=request,
                    validated_data=serializer.validated_data,
                    fingerprint=request_fingerprint(request.data),
                    idempotency_key=idempotency_key,
                )
            except MercadoPagoConflict as exc:
                return Response(
                    {"detail": str(exc), "code": "idempotency_conflict"},
                    status=status.HTTP_409_CONFLICT,
                )
            sale = Sale.objects.select_related(
                "user", "cashbox", "cashbox__register", "mercado_pago_order",
            ).prefetch_related("details__product").get(uuid=sale.uuid)
            if not replay:
                log_action(request, "SALE", "SALE", sale.uuid, {
                    "action": "MP_PENDING", "total": str(sale.total),
                    "payment_method": sale.payment_method,
                    "cashbox_id": str(sale.cashbox_id),
                })
            return Response(SaleReadSerializer(sale).data, status=status.HTTP_202_ACCEPTED)
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
                    "cashbox_id": str(sale.cashbox_id),
                    "register_id": str(sale.cashbox.register_id) if sale.cashbox.register_id else None,
                },
                context={"source": "sales", "operation": "create_sale"},
            )
            log_action(request, "SALE", "SALE", sale.uuid, {
                "total": str(sale.total),
                "payment_method": sale.payment_method,
                "items_count": sale.details.count(),
                "cashbox_id": str(sale.cashbox_id),
                "register_id": str(sale.cashbox.register_id) if sale.cashbox.register_id else None,
            })
        read_serializer = SaleReadSerializer(sale)
        return Response(read_serializer.data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(
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
        ).select_related(
            "user", "cashbox", "cashbox__register", "mercado_pago_order",
        ).prefetch_related("details__product")
        if self.request.user.role == "EMPLOYEE":
            qs = qs.filter(cashbox__status="OPEN", cashbox__opened_by=self.request.user)
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
    def post(self, request, uuid):
        external = MercadoPagoOrder.objects.filter(
            tenant_id=request.tenant_id, sale_id=uuid,
        ).select_related("sale__cashbox").first()
        if external:
            return self._cancel_external(request, external)
        with transaction.atomic():
            Tenant.objects.select_for_update().get(uuid=request.tenant_id)
            try:
                cashbox_id = Sale.objects.only("cashbox_id").get(
                    uuid=uuid,
                    tenant_id=request.tenant_id,
                ).cashbox_id
                cashbox = Cashbox.objects.select_for_update().get(
                    uuid=cashbox_id,
                    tenant_id=request.tenant_id,
                )
                sale = Sale.objects.select_for_update().get(
                    uuid=uuid,
                    tenant_id=request.tenant_id,
                    cashbox=cashbox,
                )
            except (Sale.DoesNotExist, Cashbox.DoesNotExist):
                return Response(
                    {"detail": "Sale not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if sale.status == Sale.Status.CANCELLED:
                return Response(
                    {"detail": "Sale is already cancelled."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if cashbox.status == Cashbox.Status.CLOSED:
                return Response(
                    {"detail": "Sales from a closed cashbox cannot be cancelled."},
                    status=status.HTTP_409_CONFLICT,
                )

            for detail in sale.details.select_related("product"):
                product = detail.product
                product.stock += detail.quantity
                product.save(update_fields=["stock"])

            sale.status = Sale.Status.CANCELLED
            sale.save(update_fields=["status"])

        log_action(request, "SALE", "SALE", sale.uuid, {
            "action": "CANCEL",
            "total": str(sale.total),
            "cashbox_id": str(sale.cashbox_id),
            "register_id": str(sale.cashbox.register_id) if sale.cashbox.register_id else None,
        })

        return Response(SaleReadSerializer(sale).data)

    def _cancel_external(self, request, order):
        with transaction.atomic():
            Tenant.objects.select_for_update().get(uuid=request.tenant_id)
            cashbox = Cashbox.objects.select_for_update().get(
                uuid=order.sale.cashbox_id, tenant_id=request.tenant_id,
            )
            sale = Sale.objects.select_for_update().get(
                uuid=order.sale_id, tenant_id=request.tenant_id,
            )
            order = MercadoPagoOrder.objects.select_for_update().get(uuid=order.uuid)
            if cashbox.status == Cashbox.Status.CLOSED:
                return Response(
                    {"detail": "Sales from a closed cashbox cannot be cancelled."},
                    status=status.HTTP_409_CONFLICT,
                )
            if order.state in (
                MercadoPagoOrder.State.REFUND_PENDING,
                MercadoPagoOrder.State.CANCEL_REQUESTED,
            ):
                return Response(SaleReadSerializer(sale).data, status=status.HTTP_202_ACCEPTED)
            if order.state == MercadoPagoOrder.State.ACTION_REQUIRED:
                return Response(
                    {
                        "detail": "The operation requires intervention on the Point terminal.",
                        "code": "point_action_required",
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            if sale.status == Sale.Status.CANCELLED:
                return Response({"detail": "Sale is already cancelled."}, status=400)
            if not order.external_order_id:
                return Response(
                    {"detail": "The remote order identity is still uncertain; refresh before cancelling."},
                    status=status.HTTP_409_CONFLICT,
                )
            if sale.status == Sale.Status.PENDING:
                order.cancel_idempotency_key = (
                    order.cancel_idempotency_key
                    or stable_operation_key(
                        "cancel", order.tenant_id, order.frontend_idempotency_key
                    )
                )
                order.state = MercadoPagoOrder.State.CANCEL_REQUESTED
                key = order.cancel_idempotency_key
                operation = "cancel"
            else:
                order.refund_idempotency_key = (
                    order.refund_idempotency_key
                    or stable_operation_key(
                        "refund", order.tenant_id, order.frontend_idempotency_key
                    )
                )
                order.state = MercadoPagoOrder.State.REFUND_PENDING
                key = order.refund_idempotency_key
                operation = "refund"
            order.next_retry_at = timezone.now()
            order.save()
        try:
            client = PlatformMercadoPagoClient()
            if operation == "cancel":
                client.cancel_order(
                    order.tenant_id, order.external_order_id,
                    idempotency_key=key,
                )
            else:
                client.refund_order(
                    order.tenant_id, order.external_order_id,
                    amount=order.amount, idempotency_key=key,
                )
        except PlatformBillingError as exc:
            if operation == "cancel" and exc.status_code == status.HTTP_409_CONFLICT:
                detail = exc.response_data.get("detail")
                nested = detail if isinstance(detail, dict) else {}
                MercadoPagoOrder.objects.filter(uuid=order.uuid).update(
                    state=MercadoPagoOrder.State.ACTION_REQUIRED,
                    next_retry_at=timezone.now(),
                )
                return Response(
                    {
                        "detail": nested.get("message") or exc.message,
                        "code": nested.get("code") or exc.response_data.get("code", "action_required"),
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(
                {"detail": "Mercado Pago did not confirm the request; reconciliation remains pending."},
                status=status.HTTP_202_ACCEPTED,
            )
        sale.refresh_from_db()
        return Response(SaleReadSerializer(sale).data, status=status.HTTP_202_ACCEPTED)


class SalePaymentRefreshView(APIView):
    @extend_schema(
        summary="Refrescar estado Mercado Pago", tags=["Sales"], request=None,
        responses={200: SaleReadSerializer},
    )
    def post(self, request, uuid):
        queryset = MercadoPagoOrder.objects.filter(
            tenant_id=request.tenant_id, sale_id=uuid,
        )
        if request.user.role == "EMPLOYEE":
            queryset = queryset.filter(
                sale__cashbox__status=Cashbox.Status.OPEN,
                sale__cashbox__opened_by=request.user,
            )
        order = queryset.first()
        if not order:
            return Response({"detail": "Mercado Pago sale not found."}, status=404)
        reconcile_order(order.uuid)
        sale = Sale.objects.select_related(
            "user", "cashbox", "cashbox__register", "mercado_pago_order",
        ).prefetch_related("details__product").get(uuid=uuid)
        return Response(SaleReadSerializer(sale).data)


def _uuid_query_param(request, name):
    return serializers.UUIDField().run_validation(request.query_params[name])
