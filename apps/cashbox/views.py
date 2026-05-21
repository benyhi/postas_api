from django.utils import timezone
from django.db.models import Sum
from rest_framework import generics, status, serializers
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, inline_serializer

from apps.cashbox.models import Cashbox
from apps.cashbox.serializers import (
    CashboxOpenSerializer,
    CashboxCloseSerializer,
    CashboxReadSerializer,
)
from apps.cashbox.services import send_cashbox_notification_email
from core.permissions.roles import IsAdminOrOwner
from core.utils.audit import log_action


@extend_schema(
    summary="Abrir caja",
    description="Abre una nueva caja con un monto inicial. Solo se permite una caja abierta por tenant.",
    tags=["Cashbox"],
    request=CashboxOpenSerializer,
    responses={201: CashboxReadSerializer},
    examples=[
        OpenApiExample("Abrir caja", value={"initial_amount": "5000.00"}, request_only=True),
    ],
)
class CashboxOpenView(generics.CreateAPIView):
    serializer_class = CashboxOpenSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cashbox = serializer.save()
        log_action(request, "CASHBOX", "CASHBOX", cashbox.uuid, {
            "action": "OPEN", "initial_amount": str(cashbox.initial_amount),
        })
        send_cashbox_notification_email_safely(request, cashbox)
        return Response(CashboxReadSerializer(cashbox).data, status=status.HTTP_201_CREATED)


class CashboxCloseView(APIView):
    @extend_schema(
        summary="Cerrar caja",
        description="Cierra la caja abierta del tenant. Calcula expected_amount y difference automaticamente.",
        tags=["Cashbox"],
        request=CashboxCloseSerializer,
        responses={200: CashboxReadSerializer},
        examples=[
            OpenApiExample("Cerrar caja", value={"final_amount": "12500.00"}, request_only=True),
        ],
    )
    def post(self, request):
        tenant_id = request.tenant_id
        cashbox = Cashbox.objects.filter(
            tenant_id=tenant_id, status=Cashbox.Status.OPEN,
        ).first()

        if not cashbox:
            return Response(
                {"detail": "No open cashbox found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Only the user who opened or ADMIN/OWNER can close
        is_admin_or_owner = request.user.role in ("ADMIN", "OWNER")
        if cashbox.opened_by != request.user and not is_admin_or_owner:
            return Response(
                {"detail": "Only the user who opened the cashbox or an Admin/Owner can close it."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = CashboxCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        final_amount = serializer.validated_data["final_amount"]

        # Calculate expected amount: initial + total CASH sales in this cashbox
        from apps.sales.models import Sale
        cash_total = Sale.objects.filter(
            cashbox=cashbox,
            status=Sale.Status.COMPLETED,
            payment_method=Sale.PaymentMethod.CASH,
        ).aggregate(total=Sum("total"))["total"] or 0

        expected_amount = cashbox.initial_amount + cash_total

        cashbox.final_amount = final_amount
        cashbox.expected_amount = expected_amount
        cashbox.difference = final_amount - expected_amount
        cashbox.closed_by = request.user
        cashbox.closed_at = timezone.now()
        cashbox.status = Cashbox.Status.CLOSED
        cashbox.save()

        log_action(request, "CASHBOX", "CASHBOX", cashbox.uuid, {
            "action": "CLOSE",
            "final_amount": str(final_amount),
            "expected_amount": str(expected_amount),
            "difference": str(cashbox.difference),
        })
        send_cashbox_notification_email_safely(request, cashbox)

        return Response(CashboxReadSerializer(cashbox).data)


class CashboxCurrentView(APIView):
    @extend_schema(
        summary="Caja actual",
        description="Devuelve la caja abierta actualmente para el tenant.",
        tags=["Cashbox"],
        responses={200: CashboxReadSerializer},
    )
    def get(self, request):
        cashbox = Cashbox.objects.filter(
            tenant_id=request.tenant_id, status=Cashbox.Status.OPEN,
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
            result = send_cashbox_notification_email(cashbox)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        log_action(request, "CASHBOX_EMAIL", "CASHBOX", cashbox.uuid, {
            "event": result["event"],
            "sent": result["sent"],
            "recipients_count": result["recipients_count"],
        })

        return Response({
            "detail": "Email notification sent.",
            "cashbox": cashbox.uuid,
            "event": result["event"],
            "sent": result["sent"],
            "recipients_count": result["recipients_count"],
        })

    @staticmethod
    def _can_notify(request, cashbox):
        if request.user.role in ("ADMIN", "OWNER"):
            return True
        return cashbox.opened_by_id == request.user.pk or cashbox.closed_by_id == request.user.pk


def send_cashbox_notification_email_safely(request, cashbox):
    try:
        result = send_cashbox_notification_email(cashbox)
    except ValueError as exc:
        log_action(request, "CASHBOX_EMAIL_SKIP", "CASHBOX", cashbox.uuid, {
            "reason": str(exc),
        })
    except Exception as exc:
        log_action(request, "CASHBOX_EMAIL_FAILED", "CASHBOX", cashbox.uuid, {
            "error": f"{type(exc).__name__}: {exc}",
        })
    else:
        log_action(request, "CASHBOX_EMAIL", "CASHBOX", cashbox.uuid, {
            "event": result["event"],
            "sent": result["sent"],
            "recipients_count": result["recipients_count"],
            "automatic": True,
        })


@extend_schema_view(
    list=extend_schema(
        summary="Listar cajas",
        description="Lista paginada de todas las cajas (abiertas y cerradas). Solo ADMIN u OWNER.",
        tags=["Cashbox"],
    ),
)
class CashboxListView(generics.ListAPIView):
    serializer_class = CashboxReadSerializer
    permission_classes = [IsAdminOrOwner]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Cashbox.objects.none()
        return Cashbox.objects.filter(tenant_id=self.request.tenant_id)


@extend_schema_view(
    retrieve=extend_schema(
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
        return Cashbox.objects.filter(tenant_id=self.request.tenant_id)
