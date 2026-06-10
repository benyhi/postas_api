import uuid
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.cashbox.models import Cashbox
from apps.notifications.cashbox import send_cashbox_notification_email
from apps.notifications.models import EmailDelivery
from apps.tenants.models import Tenant, TenantConfig
from apps.users.models import User


@override_settings(
    EMAIL_PROVIDER="django",
    EMAIL_FALLBACK_PROVIDER="",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class CashboxEmailNotificationTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.tenant = Tenant.objects.create(uuid=self.tenant_id, name="Test tenant")
        self.config = TenantConfig.objects.create(
            tenant=self.tenant,
            notification_email="notifications@example.com",
        )
        self.owner = User.objects.create_user(
            tenant_id=self.tenant_id,
            username="owner",
            email="owner@example.com",
            password="owner1234",
            role=User.Role.OWNER,
        )
        self.employee = User.objects.create_user(
            tenant_id=self.tenant_id,
            username="cashier",
            email="cashier@example.com",
            password="cashier1234",
            role=User.Role.EMPLOYEE,
        )
        self.billing_patcher = patch("apps.platform_billing.enforcement.PlatformBillingClient")
        self.billing_client_class = self.billing_patcher.start()
        self.addCleanup(self.billing_patcher.stop)
        self.billing_client = self.billing_client_class.return_value
        self.billing_client.check_entitlement.return_value = {"allowed": True}
        self.billing_client.check_and_consume.return_value = {"allowed": True, "recorded": True}

    def test_service_sends_open_notification_to_tenant_owner(self):
        cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.employee,
            initial_amount=Decimal("1000.00"),
        )

        result = send_cashbox_notification_email(cashbox)

        self.assertEqual(result["event"], "opened")
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["recipients_count"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["notifications@example.com"])
        self.assertIn("Caja abierta", mail.outbox[0].subject)
        self.assertIn(str(cashbox.uuid), mail.outbox[0].body)
        self.assertIn("Monto inicial: 1000.00", mail.outbox[0].body)
        html_body = _html_body(mail.outbox[0])
        self.assertIn(str(cashbox.uuid), html_body)
        self.assertIn("Monto inicial", html_body)
        delivery = EmailDelivery.objects.get()
        self.assertEqual(delivery.provider, EmailDelivery.Provider.DJANGO)
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)
        self.assertEqual(delivery.notification_type, EmailDelivery.NotificationType.CASHBOX_OPENED)
        self.billing_client.check_and_consume.assert_called_once()
        consume_call = self.billing_client.check_and_consume.call_args
        self.assertEqual(consume_call.args[0], self.tenant_id)
        self.assertEqual(consume_call.args[1], "cashbox_email_report")
        self.assertEqual(consume_call.kwargs["external_id"], f"{cashbox.uuid}:opened:manual")
        self.assertTrue(
            consume_call.kwargs["idempotency_key"].startswith(
                f"cashbox-email-report:{cashbox.uuid}:opened:manual:"
            )
        )
        self.assertEqual(consume_call.kwargs["metadata"]["source"], "manual")
        self.assertEqual(consume_call.kwargs["context"]["notification_source"], "manual")

    def test_open_endpoint_sends_notification_automatically(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.owner)}")

        response = client.post(
            "/api/v1/cashboxes/open/",
            {"initial_amount": "1000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["notifications@example.com"])
        self.assertIn("Caja abierta", mail.outbox[0].subject)
        self.assertIn("Monto inicial: 1000.00", mail.outbox[0].body)
        self.billing_client.check_and_consume.assert_called()
        cashbox = Cashbox.objects.get(tenant_id=self.tenant_id)
        consume_call = self.billing_client.check_and_consume.call_args
        self.assertEqual(
            consume_call.kwargs["idempotency_key"],
            f"cashbox-email-report:{cashbox.uuid}:opened:automatic",
        )
        self.assertEqual(consume_call.kwargs["metadata"]["source"], "automatic")
        self.assertEqual(consume_call.kwargs["context"]["notification_source"], "automatic")

    def test_open_endpoint_blocks_when_cashbox_limit_is_exceeded(self):
        self.billing_client.check_entitlement.return_value = {
            "allowed": False,
            "reason": "resource_limit_exceeded",
            "message": "Limite de cajas alcanzado.",
            "limit": 1,
            "used": 2,
            "remaining": 0,
        }
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.owner)}")

        response = client.post(
            "/api/v1/cashboxes/open/",
            {"initial_amount": "1000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["code"], "resource_limit_exceeded")
        self.assertEqual(response.data["feature_key"], "cashboxes")
        self.assertEqual(Cashbox.objects.filter(tenant_id=self.tenant_id).count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_employee_can_open_and_view_current_cashbox(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.employee)}")

        open_response = client.post(
            "/api/v1/cashboxes/open/",
            {"initial_amount": "1000.00"},
            format="json",
        )
        current_response = client.get("/api/v1/cashboxes/current/")

        self.assertEqual(open_response.status_code, 201)
        self.assertEqual(current_response.status_code, 200)
        self.assertEqual(current_response.data["uuid"], open_response.data["uuid"])

    def test_employee_cannot_list_all_cashboxes(self):
        Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.employee,
            initial_amount=Decimal("1000.00"),
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.employee)}")

        response = client.get("/api/v1/cashboxes/")

        self.assertEqual(response.status_code, 403)

    def test_close_endpoint_sends_notification_automatically(self):
        Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.employee,
            initial_amount=Decimal("1000.00"),
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.owner)}")

        response = client.post(
            "/api/v1/cashboxes/close/",
            {"final_amount": "1000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["notifications@example.com"])
        self.assertIn("Caja cerrada", mail.outbox[0].subject)
        self.assertIn("Monto final: 1000.00", mail.outbox[0].body)

    def test_endpoint_sends_closed_notification_for_cashbox(self):
        cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.employee,
            closed_by=self.owner,
            opened_at=timezone.now(),
            closed_at=timezone.now(),
            initial_amount=Decimal("1000.00"),
            final_amount=Decimal("1300.00"),
            expected_amount=Decimal("1250.00"),
            difference=Decimal("50.00"),
            status=Cashbox.Status.CLOSED,
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.owner)}")

        response = client.post(f"/api/v1/cashboxes/{cashbox.uuid}/notify-email/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["event"], "closed")
        self.assertEqual(response.data["sent"], 1)
        self.assertEqual(response.data["recipients_count"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Caja cerrada", mail.outbox[0].subject)
        self.assertIn("Monto final: 1300.00", mail.outbox[0].body)
        self.assertIn("Diferencia: 50.00", mail.outbox[0].body)
        html_body = _html_body(mail.outbox[0])
        self.assertIn("Monto final", html_body)
        self.assertIn("1300.00", html_body)
        self.assertIn("Diferencia", html_body)

    def test_manual_notification_blocks_when_email_usage_limit_is_exceeded(self):
        cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.employee,
            initial_amount=Decimal("1000.00"),
        )
        self.billing_client.check_and_consume.return_value = {
            "allowed": False,
            "reason": "quota_exceeded",
            "message": "Limite de emails de caja alcanzado.",
            "limit": 1,
            "used": 1,
            "remaining": 0,
        }
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.owner)}")

        response = client.post(f"/api/v1/cashboxes/{cashbox.uuid}/notify-email/")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["code"], "quota_exceeded")
        self.assertEqual(response.data["feature_key"], "cashbox_email_report")
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(EmailDelivery.objects.exists())

    @staticmethod
    def _access_token(user):
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        access["tenant_id"] = str(user.tenant_id)
        access["role"] = user.role
        return str(access)


def _html_body(message):
    for alternative in getattr(message, "alternatives", []):
        content = getattr(alternative, "content", None)
        mimetype = getattr(alternative, "mimetype", None)
        if isinstance(alternative, tuple):
            content, mimetype = alternative
        if mimetype == "text/html":
            return content
    return ""
