import sys
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings

from apps.notifications.models import EmailDelivery
from apps.notifications.providers.base import EmailRequest
from apps.notifications.providers.resend_provider import ResendEmailProvider
from apps.notifications.services import send_email


@override_settings(RESEND_API_KEY="re_test")
class ResendEmailProviderTests(SimpleTestCase):
    def test_resend_provider_calls_python_sdk(self):
        send_mock = MagicMock(return_value={"id": "email_123"})
        fake_resend = SimpleNamespace(api_key="", Emails=SimpleNamespace(send=send_mock))

        email_request = EmailRequest(
            subject="Caja abierta - POSTAS",
            text_body="Se registro una apertura de caja.",
            from_email="POSTAS <notificaciones@example.com>",
            to=["alerts@example.com"],
        )

        with patch.dict(sys.modules, {"resend": fake_resend}):
            result = ResendEmailProvider().send(email_request)

        self.assertEqual(fake_resend.api_key, "re_test")
        self.assertEqual(result.sent, 1)
        self.assertEqual(result.external_id, "email_123")
        send_mock.assert_called_once_with(
            {
                "from": "POSTAS <notificaciones@example.com>",
                "to": ["alerts@example.com"],
                "subject": "Caja abierta - POSTAS",
                "text": "Se registro una apertura de caja.",
            }
        )


class EmailServiceTests(TestCase):
    @override_settings(
        EMAIL_PROVIDER="resend",
        EMAIL_FALLBACK_PROVIDER="django",
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        RESEND_API_KEY="",
    )
    def test_send_email_falls_back_to_django_and_logs_attempts(self):
        result = send_email(
            tenant_id=None,
            notification_type=EmailDelivery.NotificationType.DEBUG,
            subject="Debug",
            text_body="Debug body",
            to=["alerts@example.com"],
        )

        self.assertEqual(result["provider"], EmailDelivery.Provider.DJANGO)
        self.assertEqual(len(mail.outbox), 1)

        deliveries = list(EmailDelivery.objects.order_by("created_at"))
        self.assertEqual(len(deliveries), 2)
        self.assertEqual(deliveries[0].provider, EmailDelivery.Provider.RESEND)
        self.assertEqual(deliveries[0].status, EmailDelivery.Status.FAILED)
        self.assertEqual(deliveries[1].provider, EmailDelivery.Provider.DJANGO)
        self.assertEqual(deliveries[1].status, EmailDelivery.Status.SENT)

    @override_settings(
        EMAIL_PROVIDER="resend",
        EMAIL_FALLBACK_PROVIDER="",
        RESEND_API_KEY="re_test",
        RESEND_COST_PER_1000_EMAILS="0.90",
    )
    def test_send_email_logs_resend_cost(self):
        send_mock = MagicMock(return_value={"id": "email_456"})
        fake_resend = SimpleNamespace(api_key="", Emails=SimpleNamespace(send=send_mock))

        with patch.dict(sys.modules, {"resend": fake_resend}):
            result = send_email(
                tenant_id=None,
                notification_type=EmailDelivery.NotificationType.DEBUG,
                subject="Debug",
                text_body="Debug body",
                to=["one@example.com", "two@example.com"],
            )

        self.assertEqual(result["provider"], EmailDelivery.Provider.RESEND)
        delivery = EmailDelivery.objects.get()
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)
        self.assertEqual(delivery.external_id, "email_456")
        self.assertEqual(delivery.recipient_count, 2)
        self.assertEqual(delivery.estimated_cost_usd, Decimal("0.001800"))
