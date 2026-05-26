from django.utils import timezone

from apps.cashbox.models import Cashbox
from apps.notifications.models import EmailDelivery
from apps.notifications.services import send_email
from apps.tenants.models import TenantConfig


def get_cashbox_notification_recipients(tenant_id):
    config = TenantConfig.objects.filter(tenant_id=tenant_id).first()
    if not config:
        raise ValueError("No hay TenantConfig configurado para este tenant.")
    if not config.cashbox_email_notifications_enabled:
        raise ValueError("Las notificaciones de caja por email estan desactivadas para este tenant.")
    if not config.notification_email:
        raise ValueError("TenantConfig.notification_email no esta configurado para este tenant.")
    return [config.notification_email]


def send_cashbox_notification_email(cashbox):
    recipients = get_cashbox_notification_recipients(cashbox.tenant_id)
    event = "closed" if cashbox.status == Cashbox.Status.CLOSED else "opened"
    subject = _cashbox_subject(event)
    body = _cashbox_body(cashbox, event)

    result = send_email(
        tenant_id=cashbox.tenant_id,
        notification_type=(
            EmailDelivery.NotificationType.CASHBOX_CLOSED
            if event == "closed"
            else EmailDelivery.NotificationType.CASHBOX_OPENED
        ),
        subject=subject,
        text_body=body,
        to=recipients,
        related_entity="CASHBOX",
        related_entity_id=cashbox.uuid,
        metadata={"cashbox": str(cashbox.uuid), "event": event},
    )

    return {
        "event": event,
        "sent": result["sent"],
        "recipients_count": result["recipients_count"],
        "provider": result["provider"],
        "delivery_uuid": result["delivery_uuid"],
        "estimated_cost_usd": result["estimated_cost_usd"],
    }


def _cashbox_subject(event):
    event_label = "cerrada" if event == "closed" else "abierta"
    return f"Caja {event_label} - POSTAS"


def _cashbox_body(cashbox, event):
    event_label = "cierre" if event == "closed" else "apertura"
    lines = [
        f"Se registro una {event_label} de caja.",
        "",
        f"Caja: {cashbox.uuid}",
        f"Tenant: {cashbox.tenant_id}",
        f"Estado: {cashbox.status}",
        f"Abierta por: {_user_label(cashbox.opened_by)}",
        f"Fecha de apertura: {_format_datetime(cashbox.opened_at)}",
        f"Monto inicial: {_format_money(cashbox.initial_amount)}",
    ]

    if event == "closed":
        lines.extend(
            [
                "",
                f"Cerrada por: {_user_label(cashbox.closed_by)}",
                f"Fecha de cierre: {_format_datetime(cashbox.closed_at)}",
                f"Monto final: {_format_money(cashbox.final_amount)}",
                f"Monto esperado: {_format_money(cashbox.expected_amount)}",
                f"Diferencia: {_format_money(cashbox.difference)}",
            ]
        )

    lines.extend(["", "-- POSTAS"])
    return "\n".join(lines)


def _format_datetime(value):
    if value is None:
        return "-"
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S %Z")


def _format_money(value):
    if value is None:
        return "-"
    return f"{value:.2f}"


def _user_label(user):
    if user is None:
        return "-"
    return f"{user.username} <{user.email}>"
