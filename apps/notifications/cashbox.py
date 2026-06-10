import uuid

from django.utils import timezone

from apps.cashbox.models import Cashbox
from apps.notifications.models import EmailDelivery
from apps.notifications.rendering import render_notification
from apps.notifications.services import send_email
from apps.platform_billing.enforcement import check_and_consume_billing_usage
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


def send_cashbox_notification_email(cashbox, *, billing_source="manual"):
    recipients = get_cashbox_notification_recipients(cashbox.tenant_id)
    event = "closed" if cashbox.status == Cashbox.Status.CLOSED else "opened"
    _consume_cashbox_email_report(cashbox, event, billing_source)
    subject = _cashbox_subject(event)
    text_body, html_body = _cashbox_bodies(cashbox, event)

    result = send_email(
        tenant_id=cashbox.tenant_id,
        notification_type=(
            EmailDelivery.NotificationType.CASHBOX_CLOSED
            if event == "closed"
            else EmailDelivery.NotificationType.CASHBOX_OPENED
        ),
        subject=subject,
        text_body=text_body,
        html_body=html_body,
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


def _consume_cashbox_email_report(cashbox, event, billing_source):
    if billing_source == "automatic":
        idempotency_key = f"cashbox-email-report:{cashbox.uuid}:{event}:automatic"
    else:
        idempotency_key = f"cashbox-email-report:{cashbox.uuid}:{event}:manual:{uuid.uuid4()}"

    check_and_consume_billing_usage(
        cashbox.tenant_id,
        "cashbox_email_report",
        amount=1,
        external_id=f"{cashbox.uuid}:{event}:{billing_source}",
        idempotency_key=idempotency_key,
        occurred_at=timezone.now(),
        metadata={
            "cashbox": str(cashbox.uuid),
            "event": event,
            "source": billing_source,
        },
        context={
            "source": "cashbox",
            "operation": "send_cashbox_notification_email",
            "notification_source": billing_source,
        },
    )


def _cashbox_subject(event):
    event_label = "cerrada" if event == "closed" else "abierta"
    return f"Caja {event_label} - POSTAS"


def _cashbox_bodies(cashbox, event):
    event_label = "cierre" if event == "closed" else "apertura"
    title_event_label = "cerrada" if event == "closed" else "abierta"
    rows = [
        {"label": "Caja", "value": str(cashbox.uuid)},
        {"label": "Tenant", "value": str(cashbox.tenant_id)},
        {"label": "Estado", "value": cashbox.status},
        {"label": "Abierta por", "value": _user_label(cashbox.opened_by)},
        {"label": "Fecha de apertura", "value": _format_datetime(cashbox.opened_at)},
        {"label": "Monto inicial", "value": _format_money(cashbox.initial_amount)},
    ]

    if event == "closed":
        rows.extend(
            [
                {"label": "Cerrada por", "value": _user_label(cashbox.closed_by)},
                {"label": "Fecha de cierre", "value": _format_datetime(cashbox.closed_at)},
                {"label": "Monto final", "value": _format_money(cashbox.final_amount)},
                {"label": "Monto esperado", "value": _format_money(cashbox.expected_amount)},
                {"label": "Diferencia", "value": _format_money(cashbox.difference)},
            ]
        )

    return render_notification(
        "cashbox_notification",
        {
            "brand_name": "POSTAS",
            "title": f"Caja {title_event_label}",
            "preheader": f"Se registro una {event_label} de caja en POSTAS.",
            "intro": f"Se registro una {event_label} de caja.",
            "rows": rows,
        },
    )


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
