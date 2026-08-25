import logging
from decimal import Decimal

from django.utils import timezone
from django.db import IntegrityError, transaction
from rest_framework import generics, status, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)

from apps.cashbox.models import Cashbox, CashRegister
from apps.cashbox.serializers import (
    CashRegisterSerializer,
    CashboxOpenSerializer,
    CashboxCloseSerializer,
    CashboxReadSerializer,
)
from apps.notifications.cashbox import send_cashbox_notification_email
from apps.platform_billing.enforcement import check_billing_entitlement
from apps.tenants.models import Tenant
from core.permissions.roles import IsAdminOrOwner, IsAdminOrOwnerOrReadOnly
from core.utils.audit import log_action


logger = logging.getLogger(__name__)


@extend_schema_view(
    get=extend_schema(summary="Listar terminales activas", tags=["Cash registers"]),
    post=extend_schema(summary="Crear terminal", tags=["Cash registers"]),
)
class CashRegisterListCreateView(generics.ListCreateAPIView):
    serializer_class = CashRegisterSerializer
    permission_classes = [IsAdminOrOwnerOrReadOnly]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CashRegister.objects.none()
        return CashRegister.objects.filter(tenant_id=self.request.tenant_id, active=True)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                Tenant.objects.select_for_update().get(uuid=request.tenant_id)
                cash_register = serializer.save()
        except IntegrityError:
            return Response(
                {"detail": "A cash register with this name already exists."},
                status=status.HTTP_409_CONFLICT,
            )
        log_action(request, "CREATE", "CASH_REGISTER", cash_register.uuid, {
            "name": cash_register.name,
            "active": cash_register.active,
            "register_id": str(cash_register.uuid),
        })
        return Response(self.get_serializer(cash_register).data, status=status.HTTP_201_CREATED)


@extend_schema_view(
    get=extend_schema(summary="Detalle de terminal", tags=["Cash registers"]),
    put=extend_schema(summary="Actualizar terminal", tags=["Cash registers"]),
    patch=extend_schema(summary="Renombrar o desactivar terminal", tags=["Cash registers"]),
)
class CashRegisterDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = CashRegisterSerializer
    permission_classes = [IsAdminOrOwnerOrReadOnly]
    lookup_field = "uuid"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CashRegister.objects.none()
        queryset = CashRegister.objects.filter(tenant_id=self.request.tenant_id)
        if self.request.user.role not in ("ADMIN", "OWNER"):
            queryset = queryset.filter(active=True)
        return queryset

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        with transaction.atomic():
            Tenant.objects.select_for_update().get(uuid=request.tenant_id)
            cash_register = CashRegister.objects.select_for_update().filter(
                uuid=kwargs["uuid"],
                tenant_id=request.tenant_id,
            ).first()
            if not cash_register:
                return Response(
                    {"detail": "Cash register not found."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            old_name = cash_register.name
            old_active = cash_register.active
            serializer = self.get_serializer(
                cash_register,
                data=request.data,
                partial=partial,
            )
            serializer.is_valid(raise_exception=True)
            will_be_active = serializer.validated_data.get("active", cash_register.active)
            if not will_be_active and Cashbox.objects.filter(
                tenant_id=request.tenant_id,
                register=cash_register,
                status=Cashbox.Status.OPEN,
            ).exists():
                return Response(
                    {"detail": "An open cashbox is using this cash register."},
                    status=status.HTTP_409_CONFLICT,
                )
            cash_register = serializer.save()

        event = "DEACTIVATE" if old_active and not cash_register.active else "UPDATE"
        log_action(request, "UPDATE", "CASH_REGISTER", cash_register.uuid, {
            "action": event,
            "register_id": str(cash_register.uuid),
            "old_name": old_name,
            "name": cash_register.name,
            "old_active": old_active,
            "active": cash_register.active,
        })
        return Response(self.get_serializer(cash_register).data)


@extend_schema(
    summary="Abrir caja",
    description=(
        "Abre una sesion en una terminal activa. Cada usuario y terminal solo pueden "
        "tener una sesion abierta; el limite simultaneo depende del plan."
    ),
    tags=["Cashbox"],
    request=CashboxOpenSerializer,
    responses={201: CashboxReadSerializer},
    examples=[
        OpenApiExample(
            "Abrir caja",
            value={"register_id": "uuid-de-la-terminal", "initial_amount": "5000.00"},
            request_only=True,
        ),
    ],
)
class CashboxOpenView(generics.CreateAPIView):
    serializer_class = CashboxOpenSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        register = serializer.validated_data["register"]
        try:
            with transaction.atomic():
                Tenant.objects.select_for_update().get(uuid=request.tenant_id)
                if not CashRegister.objects.filter(
                    uuid=register.uuid,
                    tenant_id=request.tenant_id,
                    active=True,
                ).exists():
                    return Response(
                        {"detail": "Active cash register not found."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if Cashbox.objects.filter(
                    tenant_id=request.tenant_id,
                    opened_by=request.user,
                    status=Cashbox.Status.OPEN,
                ).exists():
                    return Response(
                        {"detail": "The user already has an open cashbox."},
                        status=status.HTTP_409_CONFLICT,
                    )
                if Cashbox.objects.filter(
                    tenant_id=request.tenant_id,
                    register=register,
                    status=Cashbox.Status.OPEN,
                ).exists():
                    return Response(
                        {"detail": "The cash register already has an open cashbox."},
                        status=status.HTTP_409_CONFLICT,
                    )
                projected_count = Cashbox.objects.filter(
                    tenant_id=request.tenant_id,
                    status=Cashbox.Status.OPEN,
                ).count() + 1
                check_billing_entitlement(
                    request.tenant_id,
                    "cashboxes",
                    resource_count=projected_count,
                    context={
                        "source": "cashbox",
                        "operation": "open_cashbox",
                        "register_id": str(register.uuid),
                    },
                )
                cashbox = serializer.save()
        except IntegrityError:
            return Response(
                {"detail": "The user or cash register already has an open cashbox."},
                status=status.HTTP_409_CONFLICT,
            )
        log_action(request, "CASHBOX", "CASHBOX", cashbox.uuid, {
            "action": "OPEN",
            "initial_amount": str(cashbox.initial_amount),
            "cashbox_id": str(cashbox.uuid),
            "register_id": str(cashbox.register_id),
        })
        send_cashbox_notification_email_safely(request, cashbox)
        return Response(CashboxReadSerializer(cashbox).data, status=status.HTTP_201_CREATED)


class CashboxCloseView(APIView):
    @extend_schema(
        summary="Cerrar caja",
        description=(
            "Cierra la sesion abierta del usuario. ADMIN/OWNER pueden enviar cashbox_id "
            "para cerrar administrativamente otra sesion del tenant."
        ),
        tags=["Cashbox"],
        request=CashboxCloseSerializer,
        responses={200: CashboxReadSerializer},
        examples=[
            OpenApiExample("Cerrar caja", value={"final_amount": "12500.00"}, request_only=True),
        ],
    )
    def post(self, request):
        serializer = CashboxCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cashbox_id = serializer.validated_data.get("cashbox_id")
        if cashbox_id and request.user.role not in ("ADMIN", "OWNER"):
            return Response(
                {"detail": "Only an Admin/Owner can close another user's cashbox."},
                status=status.HTTP_403_FORBIDDEN,
            )
        final_amount = serializer.validated_data["final_amount"]
        with transaction.atomic():
            Tenant.objects.select_for_update().get(uuid=request.tenant_id)
            queryset = Cashbox.objects.select_for_update().filter(
                tenant_id=request.tenant_id,
                status=Cashbox.Status.OPEN,
            )
            if cashbox_id:
                queryset = queryset.filter(uuid=cashbox_id)
            else:
                queryset = queryset.filter(opened_by=request.user)
            cashbox = queryset.first()
            if not cashbox:
                return Response(
                    {"detail": "No open cashbox found."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            cash_total = _cash_total_for_cashbox(cashbox)
            expected_amount = cashbox.initial_amount + cash_total
            cashbox.final_amount = final_amount
            cashbox.expected_amount = expected_amount
            cashbox.difference = final_amount - expected_amount
            cashbox.closed_by = request.user
            cashbox.closed_at = timezone.now()
            cashbox.status = Cashbox.Status.CLOSED
            cashbox.save(update_fields=[
                "final_amount", "expected_amount", "difference", "closed_by",
                "closed_at", "status",
            ])

        log_action(request, "CASHBOX", "CASHBOX", cashbox.uuid, {
            "action": "CLOSE",
            "final_amount": str(final_amount),
            "expected_amount": str(expected_amount),
            "difference": str(cashbox.difference),
            "cashbox_id": str(cashbox.uuid),
            "register_id": str(cashbox.register_id) if cashbox.register_id else None,
        })
        send_cashbox_notification_email_safely(request, cashbox)

        return Response(CashboxReadSerializer(cashbox).data)


class CashboxCurrentView(APIView):
    @extend_schema(
        summary="Caja actual",
        description="Devuelve la sesion abierta del usuario autenticado.",
        tags=["Cashbox"],
        responses={200: CashboxReadSerializer},
    )
    def get(self, request):
        cashbox = Cashbox.objects.filter(
            tenant_id=request.tenant_id,
            opened_by=request.user,
            status=Cashbox.Status.OPEN,
        ).first()
        if not cashbox:
            return Response(
                {"detail": "No open cashbox."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(CashboxReadSerializer(cashbox).data)


class CashboxNotifyEmailView(APIView):
    @extend_schema(
        summary="Enviar email de notificacion de caja",
        description=(
            "Envia al OWNER del tenant un email con la informacion de apertura "
            "o cierre de una caja, segun el estado actual de la caja."
        ),
        tags=["Cashbox"],
        responses={
            200: inline_serializer(
                name="CashboxNotifyEmailResponse",
                fields={
                    "detail": serializers.CharField(),
                    "cashbox": serializers.UUIDField(),
                    "event": serializers.CharField(),
                    "sent": serializers.IntegerField(),
                    "recipients_count": serializers.IntegerField(),
                    "provider": serializers.CharField(),
                    "delivery_uuid": serializers.UUIDField(),
                    "estimated_cost_usd": serializers.DecimalField(max_digits=12, decimal_places=6),
                },
            ),
            400: inline_serializer(
                name="CashboxNotifyEmailError",
                fields={"detail": serializers.CharField()},
            ),
            403: inline_serializer(
                name="CashboxNotifyEmailForbidden",
                fields={"detail": serializers.CharField()},
            ),
            404: inline_serializer(
                name="CashboxNotifyEmailNotFound",
                fields={"detail": serializers.CharField()},
            ),
        },
    )
    def post(self, request, uuid):
        cashbox = (
            Cashbox.objects.select_related("opened_by", "closed_by")
            .filter(uuid=uuid, tenant_id=request.tenant_id)
            .first()
        )
        if not cashbox:
            return Response(
                {"detail": "Cashbox not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not self._can_notify(request, cashbox):
            return Response(
                {"detail": "Only the user who opened/closed the cashbox or an Admin/Owner can notify it."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            result = send_cashbox_notification_email(cashbox, billing_source="manual")
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        log_action(request, "CASHBOX_EMAIL", "CASHBOX", cashbox.uuid, {
            "event": result["event"],
            "sent": result["sent"],
            "recipients_count": result["recipients_count"],
            "provider": result["provider"],
            "delivery_uuid": str(result["delivery_uuid"]),
            "estimated_cost_usd": str(result["estimated_cost_usd"]),
            "cashbox_id": str(cashbox.uuid),
            "register_id": str(cashbox.register_id) if cashbox.register_id else None,
        })

        return Response({
            "detail": "Email notification sent.",
            "cashbox": cashbox.uuid,
            "event": result["event"],
            "sent": result["sent"],
            "recipients_count": result["recipients_count"],
            "provider": result["provider"],
            "delivery_uuid": result["delivery_uuid"],
            "estimated_cost_usd": result["estimated_cost_usd"],
        })

    @staticmethod
    def _can_notify(request, cashbox):
        if request.user.role in ("ADMIN", "OWNER"):
            return True
        return cashbox.opened_by_id == request.user.pk or cashbox.closed_by_id == request.user.pk


def send_cashbox_notification_email_safely(request, cashbox):
    try:
        result = send_cashbox_notification_email(cashbox, billing_source="automatic")
    except ValueError as exc:
        logger.warning(
            "Cashbox email skipped for cashbox %s tenant %s: %s",
            cashbox.uuid,
            cashbox.tenant_id,
            exc,
        )
        log_action(request, "CASHBOX_EMAIL_SKIP", "CASHBOX", cashbox.uuid, {
            "reason": str(exc),
            "cashbox_id": str(cashbox.uuid),
            "register_id": str(cashbox.register_id) if cashbox.register_id else None,
        })
    except Exception as exc:
        logger.exception(
            "Cashbox email failed for cashbox %s tenant %s",
            cashbox.uuid,
            cashbox.tenant_id,
        )
        log_action(request, "CASHBOX_EMAIL_FAILED", "CASHBOX", cashbox.uuid, {
            "error": f"{type(exc).__name__}: {exc}",
            "cashbox_id": str(cashbox.uuid),
            "register_id": str(cashbox.register_id) if cashbox.register_id else None,
        })
    else:
        logger.info(
            "Cashbox email sent for cashbox %s tenant %s event %s",
            cashbox.uuid,
            cashbox.tenant_id,
            result["event"],
        )
        log_action(request, "CASHBOX_EMAIL", "CASHBOX", cashbox.uuid, {
            "event": result["event"],
            "sent": result["sent"],
            "recipients_count": result["recipients_count"],
            "provider": result["provider"],
            "delivery_uuid": str(result["delivery_uuid"]),
            "estimated_cost_usd": str(result["estimated_cost_usd"]),
            "automatic": True,
            "cashbox_id": str(cashbox.uuid),
            "register_id": str(cashbox.register_id) if cashbox.register_id else None,
        })


@extend_schema_view(
    get=extend_schema(
        summary="Listar cajas",
        description="Lista paginada de todas las cajas (abiertas y cerradas). Solo ADMIN u OWNER.",
        tags=["Cashbox"],
        parameters=[
            OpenApiParameter(name="register_id", description="UUID de la terminal", type=str, required=False),
            OpenApiParameter(name="user_id", description="UUID del operador que abrio", type=str, required=False),
            OpenApiParameter(name="status", description="Estado de la sesion", type=str, enum=["OPEN", "CLOSED"], required=False),
        ],
    ),
)
class CashboxListView(generics.ListAPIView):
    serializer_class = CashboxReadSerializer
    permission_classes = [IsAdminOrOwner]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Cashbox.objects.none()
        queryset = Cashbox.objects.filter(tenant_id=self.request.tenant_id).select_related("register")
        if self.request.query_params.get("register_id"):
            queryset = queryset.filter(register_id=_uuid_query_param(self.request, "register_id"))
        if self.request.query_params.get("user_id"):
            queryset = queryset.filter(opened_by_id=_uuid_query_param(self.request, "user_id"))
        if self.request.query_params.get("status"):
            session_status = serializers.ChoiceField(choices=Cashbox.Status.choices).run_validation(
                self.request.query_params["status"]
            )
            queryset = queryset.filter(status=session_status)
        return queryset


@extend_schema_view(
    get=extend_schema(
        summary="Detalle de caja",
        description="Devuelve el detalle de una caja por UUID. Solo ADMIN u OWNER.",
        tags=["Cashbox"],
    ),
)
class CashboxDetailView(generics.RetrieveAPIView):
    serializer_class = CashboxReadSerializer
    permission_classes = [IsAdminOrOwner]
    lookup_field = "uuid"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Cashbox.objects.none()
        return Cashbox.objects.filter(tenant_id=self.request.tenant_id).select_related("register")


def _cash_total_for_cashbox(cashbox):
    from apps.sales.models import Sale

    total = Decimal("0")
    sales = Sale.objects.filter(
        cashbox=cashbox,
        status=Sale.Status.COMPLETED,
    ).only("payment_method", "payments", "total")
    for sale in sales:
        if sale.payment_method == Sale.PaymentMethod.CASH:
            total += sale.total
        elif sale.payment_method == Sale.PaymentMethod.MIXED:
            for payment in sale.payments or []:
                if payment.get("method") == Sale.PaymentMethod.CASH:
                    total += Decimal(str(payment.get("amount", "0")))
    return total


def _uuid_query_param(request, name):
    return serializers.UUIDField().run_validation(request.query_params[name])
