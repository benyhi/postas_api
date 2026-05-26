from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone

from apps.notifications.models import EmailDelivery
from apps.notifications.providers.base import EmailRequest
from apps.notifications.providers.registry import get_email_provider


class EmailSendError(Exception):
    pass


def send_email(
    *,
    tenant_id,
    notification_type,
    subject,
    text_body,
    to,
    from_email=None,
    html_body="",
    cc=None,
    bcc=None,
    reply_to=None,
    metadata=None,
    related_entity="",
    related_entity_id=None,
    allow_fallback=True,
):
    recipients = _clean_recipients(to)
    if not recipients:
        raise ValueError("No hay destinatarios configurados para el email.")

    email_request = EmailRequest(
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=recipients,
        cc=_clean_recipients(cc or []),
        bcc=_clean_recipients(bcc or []),
        reply_to=_clean_recipients(reply_to or []),
        metadata={**(metadata or {}), "notification_type": notification_type},
    )

    provider_names = _provider_chain(allow_fallback=allow_fallback)
    last_error = None

    for provider_name in provider_names:
        delivery = EmailDelivery.objects.create(
            tenant_id=tenant_id,
            notification_type=notification_type,
            provider=provider_name,
            subject=subject,
            from_email=email_request.from_email,
            to_emails=recipients,
            recipient_count=len(recipients),
            related_entity=related_entity,
            related_entity_id=related_entity_id,
            metadata=metadata or {},
        )

        try:
            provider = get_email_provider(provider_name)
            result = provider.send(email_request)
        except Exception as exc:
            last_error = exc
            delivery.status = EmailDelivery.Status.FAILED
            delivery.error_message = f"{type(exc).__name__}: {exc}"
            delivery.save(update_fields=["status", "error_message", "updated_at"])
            continue

        delivery.status = EmailDelivery.Status.SENT
        delivery.external_id = result.external_id
        delivery.provider_response = result.response
        delivery.estimated_cost_usd = _estimated_cost(provider_name, len(recipients))
        delivery.sent_at = timezone.now()
        delivery.save(
            update_fields=[
                "status",
                "external_id",
                "provider_response",
                "estimated_cost_usd",
                "sent_at",
                "updated_at",
            ]
        )

        return {
            "provider": provider_name,
            "sent": result.sent,
            "recipients_count": len(recipients),
            "delivery_uuid": delivery.uuid,
            "estimated_cost_usd": delivery.estimated_cost_usd,
            "external_id": result.external_id,
        }

    raise EmailSendError(f"No se pudo enviar el email: {last_error}") from last_error


def _provider_chain(*, allow_fallback):
    primary = settings.EMAIL_PROVIDER or "resend"
    providers = [primary]

    fallback = settings.EMAIL_FALLBACK_PROVIDER
    if allow_fallback and settings.EMAIL_PROVIDER_FALLBACK_ENABLED and fallback and fallback != primary:
        providers.append(fallback)

    return providers


def _clean_recipients(recipients):
    if isinstance(recipients, str):
        recipients = [recipients]
    return [email.strip() for email in recipients if email and email.strip()]


def _estimated_cost(provider_name, recipient_count):
    setting_name = f"{provider_name.upper()}_COST_PER_1000_EMAILS"
    fallback_setting_name = f"{provider_name.upper()}_EMAIL_COST_PER_1000_EMAILS"
    raw_value = getattr(
        settings,
        setting_name,
        getattr(settings, fallback_setting_name, "0"),
    )
    try:
        cost_per_1000 = Decimal(str(raw_value))
    except (InvalidOperation, TypeError):
        cost_per_1000 = Decimal("0")

    return (cost_per_1000 * Decimal(recipient_count) / Decimal("1000")).quantize(Decimal("0.000001"))
