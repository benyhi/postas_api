from django.conf import settings

from apps.notifications.models import EmailDelivery
from apps.notifications.services import send_email


def send_password_reset_email(user, reset_url):
    body = (
        f"Hola {user.username},\n\n"
        f"Recibiste este email porque se solicito restablecer tu contrasena.\n\n"
        f"Hace click en el siguiente enlace:\n{reset_url}\n\n"
        f"Este enlace expira en 24 horas.\n"
        f"Si no lo solicitaste, ignora este email.\n\n"
        f"-- POSTAS"
    )

    return send_email(
        tenant_id=user.tenant_id,
        notification_type=EmailDelivery.NotificationType.PASSWORD_RESET,
        subject="Restablecer contrasena - POSTAS",
        text_body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
        related_entity="USER",
        related_entity_id=user.uuid,
        metadata={"user": str(user.uuid)},
    )
