import uuid
from decimal import Decimal

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
        delivery = EmailDelivery.objects.get()
        self.assertEqual(delivery.provider, EmailDelivery.Provider.DJANGO)
        self.assertEqual(delivery.status, EmailDelivery.Status.SENT)
        self.assertEqual(delivery.notification_type, EmailDelivery.NotificationType.CASHBOX_OPENED)

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

    @staticmethod
    def _access_token(user):
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        access["tenant_id"] = str(user.tenant_id)
        access["role"] = user.role
        return str(access)
