from django.conf import settings

from apps.notifications.models import EmailDelivery
from apps.notifications.rendering import render_notification
from apps.notifications.services import send_email


def send_password_reset_email(user, reset_url):
    text_body, html_body = render_notification(
        "password_reset",
        {
            "brand_name": "POSTAS",
            "title": "Restablecer contrasena",
            "preheader": "Usa este enlace para restablecer tu contrasena en POSTAS.",
            "username": user.username,
            "reset_url": reset_url,
            "expiration": "24 horas",
        },
    )

    return send_email(
        tenant_id=user.tenant_id,
        notification_type=EmailDelivery.NotificationType.PASSWORD_RESET,
        subject="Restablecer contrasena - POSTAS",
        text_body=text_body,
        html_body=html_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
        related_entity="USER",
        related_entity_id=user.uuid,
        metadata={"user": str(user.uuid)},
    )
