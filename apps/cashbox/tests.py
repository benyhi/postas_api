import uuid
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.cashbox.models import Cashbox, CashRegister
from apps.audit.models import AuditLog
from apps.notifications.cashbox import send_cashbox_notification_email
from apps.notifications.models import EmailDelivery
from apps.sales.models import Sale
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
        self.register = CashRegister.objects.create(
            tenant_id=self.tenant_id,
            name="Caja principal",
        )
        self.billing_patcher = patch("apps.platform_billing.enforcement.PlatformBillingClient")
        self.billing_client_class = self.billing_patcher.start()
        self.addCleanup(self.billing_patcher.stop)
        self.billing_client = self.billing_client_class.return_value
        self.billing_client.check_entitlement.return_value = {"allowed": True}
        self.billing_client.check_and_consume.return_value = {"allowed": True, "recorded": True}

    def test_service_sends_open_notification_to_tenant_owner(self):
        opened_at = datetime(2026, 6, 16, 22, 24, 31, tzinfo=datetime_timezone.utc)
        cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            register=self.register,
            opened_by=self.employee,
            initial_amount=Decimal("1000.00"),
        )
        Cashbox.objects.filter(pk=cashbox.pk).update(opened_at=opened_at)
        cashbox.refresh_from_db()

        result = send_cashbox_notification_email(cashbox)

        self.assertEqual(result["event"], "opened")
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["recipients_count"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["notifications@example.com"])
        self.assertIn("Caja abierta", mail.outbox[0].subject)
        self.assertIn("Terminal: Caja principal", mail.outbox[0].body)
        self.assertNotIn("\nCaja:", mail.outbox[0].body)
        self.assertNotIn("\nTenant:", mail.outbox[0].body)
        self.assertNotIn(str(cashbox.uuid), mail.outbox[0].body)
        self.assertNotIn(str(self.tenant_id), mail.outbox[0].body)
        self.assertIn("Fecha de apertura: 16-06-26 | 22:24 hs.", mail.outbox[0].body)
        self.assertIn("Monto inicial: $1000.00", mail.outbox[0].body)
        self.assertNotIn("Fecha de cierre:", mail.outbox[0].body)
        self.assertNotIn("Monto final:", mail.outbox[0].body)
        html_body = _html_body(mail.outbox[0])
        self.assertIn("Caja principal", html_body)
        self.assertNotRegex(html_body, r">\s*Caja\s*</td>")
        self.assertNotRegex(html_body, r">\s*Tenant\s*</td>")
        self.assertNotIn(str(cashbox.uuid), html_body)
        self.assertNotIn(str(self.tenant_id), html_body)
        self.assertIn("16-06-26 | 22:24 hs.", html_body)
        self.assertIn("Monto inicial", html_body)
        self.assertIn("$1000.00", html_body)
        self.assertNotIn("Fecha de cierre", html_body)
        self.assertNotIn("Monto final", html_body)
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
            {"register_id": str(self.register.uuid), "initial_amount": "1000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["notifications@example.com"])
        self.assertIn("Caja abierta", mail.outbox[0].subject)
        self.assertIn("Monto inicial: $1000.00", mail.outbox[0].body)
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
            {"register_id": str(self.register.uuid), "initial_amount": "1000.00"},
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
            {"register_id": str(self.register.uuid), "initial_amount": "1000.00"},
            format="json",
        )
        current_response = client.get("/api/v1/cashboxes/current/")

        self.assertEqual(open_response.status_code, 201)
        self.assertEqual(current_response.status_code, 200)
        self.assertEqual(current_response.data["uuid"], open_response.data["uuid"])

    def test_employee_cannot_list_all_cashboxes(self):
        cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.employee,
            initial_amount=Decimal("1000.00"),
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.employee)}")

        response = client.get("/api/v1/cashboxes/")

        self.assertEqual(response.status_code, 403)

    def test_close_endpoint_sends_notification_automatically(self):
        cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            register=self.register,
            opened_by=self.employee,
            initial_amount=Decimal("1000.00"),
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.owner)}")

        response = client.post(
            "/api/v1/cashboxes/close/",
            {"cashbox_id": str(cashbox.uuid), "final_amount": "1000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["notifications@example.com"])
        self.assertIn("Caja cerrada", mail.outbox[0].subject)
        self.assertIn("Terminal: Caja principal", mail.outbox[0].body)
        self.assertIn("Monto final: $1000.00", mail.outbox[0].body)

    def test_endpoint_sends_closed_notification_for_cashbox(self):
        opened_at = datetime(2026, 6, 16, 22, 24, 31, tzinfo=datetime_timezone.utc)
        closed_at = datetime(2026, 6, 16, 22, 26, 2, tzinfo=datetime_timezone.utc)
        cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            register=self.register,
            opened_by=self.employee,
            closed_by=self.owner,
            closed_at=closed_at,
            initial_amount=Decimal("15400.00"),
            final_amount=Decimal("103194.00"),
            expected_amount=Decimal("118594.00"),
            difference=Decimal("-15400.00"),
            status=Cashbox.Status.CLOSED,
        )
        Cashbox.objects.filter(pk=cashbox.pk).update(opened_at=opened_at)
        cashbox.refresh_from_db()
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.owner)}")

        response = client.post(f"/api/v1/cashboxes/{cashbox.uuid}/notify-email/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["event"], "closed")
        self.assertEqual(response.data["sent"], 1)
        self.assertEqual(response.data["recipients_count"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Caja cerrada", mail.outbox[0].subject)
        self.assertIn("Terminal: Caja principal", mail.outbox[0].body)
        self.assertNotIn("\nCaja:", mail.outbox[0].body)
        self.assertNotIn("\nTenant:", mail.outbox[0].body)
        self.assertIn("Fecha de apertura: 16-06-26 | 22:24 hs.", mail.outbox[0].body)
        self.assertIn("Fecha de cierre: 16-06-26 | 22:26 hs.", mail.outbox[0].body)
        self.assertIn("Monto inicial: $15400.00", mail.outbox[0].body)
        self.assertIn("Monto final: $103194.00", mail.outbox[0].body)
        self.assertIn("Monto esperado: $118594.00", mail.outbox[0].body)
        self.assertIn("Diferencia: $-15400.00", mail.outbox[0].body)
        html_body = _html_body(mail.outbox[0])
        self.assertIn("Caja principal", html_body)
        self.assertNotRegex(html_body, r">\s*Caja\s*</td>")
        self.assertNotRegex(html_body, r">\s*Tenant\s*</td>")
        self.assertNotIn(str(cashbox.uuid), html_body)
        self.assertNotIn(str(self.tenant_id), html_body)
        for expected_value in (
            "16-06-26 | 22:24 hs.",
            "16-06-26 | 22:26 hs.",
            "$15400.00",
            "$103194.00",
            "$118594.00",
            "$-15400.00",
        ):
            self.assertIn(expected_value, html_body)

    def test_historical_cashbox_without_register_uses_terminal_fallback(self):
        cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.employee,
            initial_amount=Decimal("1000.00"),
        )

        send_cashbox_notification_email(cashbox)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Terminal: -", mail.outbox[0].body)
        html_body = _html_body(mail.outbox[0])
        self.assertRegex(
            html_body,
            r">\s*Terminal\s*</td>\s*<td[^>]*>\s*-\s*</td>",
        )

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


class MultiRegisterCashboxTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(uuid=uuid.uuid4(), name="Multi register tenant")
        self.tenant_id = self.tenant.uuid
        self.owner = self._user("owner-multi", User.Role.OWNER)
        self.employee_one = self._user("cashier-one", User.Role.EMPLOYEE)
        self.employee_two = self._user("cashier-two", User.Role.EMPLOYEE)
        self.register_one = CashRegister.objects.create(
            tenant_id=self.tenant_id,
            name="Terminal 1",
        )
        self.register_two = CashRegister.objects.create(
            tenant_id=self.tenant_id,
            name="Terminal 2",
        )
        self.other_tenant = Tenant.objects.create(uuid=uuid.uuid4(), name="Other tenant")
        self.other_register = CashRegister.objects.create(
            tenant_id=self.other_tenant.uuid,
            name="Other terminal",
        )
        self.billing_patcher = patch("apps.platform_billing.enforcement.PlatformBillingClient")
        self.billing_client_class = self.billing_patcher.start()
        self.addCleanup(self.billing_patcher.stop)
        self.billing_client = self.billing_client_class.return_value
        self.billing_client.check_entitlement.return_value = {"allowed": True}
        self.billing_client.check_and_consume.return_value = {"allowed": True, "recorded": True}

    def test_authenticated_users_list_only_active_registers_in_their_tenant(self):
        inactive = CashRegister.objects.create(
            tenant_id=self.tenant_id,
            name="Inactive",
            active=False,
        )

        response = self._client(self.employee_one).get("/api/v1/cash-registers/")

        self.assertEqual(response.status_code, 200)
        returned = {item["uuid"] for item in response.data["results"]}
        self.assertEqual(returned, {str(self.register_one.uuid), str(self.register_two.uuid)})
        self.assertNotIn(str(inactive.uuid), returned)
        self.assertNotIn(str(self.other_register.uuid), returned)

    def test_register_names_are_unique_per_tenant_but_reusable_across_tenants(self):
        CashRegister.objects.create(
            tenant_id=self.other_tenant.uuid,
            name=self.register_one.name,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            CashRegister.objects.create(
                tenant_id=self.tenant_id,
                name=self.register_one.name,
            )

    def test_only_admin_or_owner_can_create_rename_and_deactivate_registers(self):
        employee_response = self._client(self.employee_one).post(
            "/api/v1/cash-registers/",
            {"name": "Forbidden"},
            format="json",
        )
        owner_client = self._client(self.owner)
        create_response = owner_client.post(
            "/api/v1/cash-registers/",
            {"name": "Terminal 3"},
            format="json",
        )
        register_id = create_response.data["uuid"]
        rename_response = owner_client.patch(
            f"/api/v1/cash-registers/{register_id}/",
            {"name": "Terminal renamed"},
            format="json",
        )
        deactivate_response = owner_client.patch(
            f"/api/v1/cash-registers/{register_id}/",
            {"active": False},
            format="json",
        )
        delete_response = owner_client.delete(f"/api/v1/cash-registers/{register_id}/")

        self.assertEqual(employee_response.status_code, 403)
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(rename_response.status_code, 200)
        self.assertEqual(deactivate_response.status_code, 200)
        self.assertFalse(deactivate_response.data["active"])
        self.assertEqual(delete_response.status_code, 405)
        logs = AuditLog.objects.filter(entity=AuditLog.Entity.CASH_REGISTER, entity_id=register_id)
        self.assertEqual(logs.filter(action=AuditLog.Action.CREATE).count(), 1)
        self.assertEqual(logs.filter(action=AuditLog.Action.UPDATE).count(), 2)
        self.assertTrue(logs.filter(metadata__action="DEACTIVATE").exists())

    def test_open_register_cannot_be_deactivated(self):
        cashbox = self._open(self.employee_one, self.register_one)

        response = self._client(self.owner).patch(
            f"/api/v1/cash-registers/{self.register_one.uuid}/",
            {"active": False},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.register_one.refresh_from_db()
        self.assertTrue(self.register_one.active)
        self.assertEqual(cashbox.status, Cashbox.Status.OPEN)

    def test_owner_cannot_retrieve_or_update_another_tenant_register(self):
        owner_client = self._client(self.owner)

        retrieve = owner_client.get(f"/api/v1/cash-registers/{self.other_register.uuid}/")
        update = owner_client.patch(
            f"/api/v1/cash-registers/{self.other_register.uuid}/",
            {"name": "Cross-tenant rename"},
            format="json",
        )

        self.assertEqual(retrieve.status_code, 404)
        self.assertEqual(update.status_code, 404)
        self.other_register.refresh_from_db()
        self.assertEqual(self.other_register.name, "Other terminal")

    def test_open_requires_an_active_register(self):
        inactive = CashRegister.objects.create(
            tenant_id=self.tenant_id,
            name="Inactive terminal",
            active=False,
        )
        client = self._client(self.employee_one)

        missing = client.post(
            "/api/v1/cashboxes/open/",
            {"initial_amount": "100.00"},
            format="json",
        )
        inactive_response = client.post(
            "/api/v1/cashboxes/open/",
            {"register_id": str(inactive.uuid), "initial_amount": "100.00"},
            format="json",
        )

        self.assertEqual(missing.status_code, 400)
        self.assertIn("register_id", missing.data)
        self.assertEqual(inactive_response.status_code, 400)
        self.assertFalse(Cashbox.objects.filter(tenant_id=self.tenant_id).exists())

    def test_two_users_can_open_different_registers_and_current_is_user_scoped(self):
        first = self._client(self.employee_one).post(
            "/api/v1/cashboxes/open/",
            {"register_id": str(self.register_one.uuid), "initial_amount": "100.00"},
            format="json",
        )
        second = self._client(self.employee_two).post(
            "/api/v1/cashboxes/open/",
            {"register_id": str(self.register_two.uuid), "initial_amount": "200.00"},
            format="json",
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(self._client(self.employee_one).get("/api/v1/cashboxes/current/").data["uuid"], first.data["uuid"])
        self.assertEqual(self._client(self.employee_two).get("/api/v1/cashboxes/current/").data["uuid"], second.data["uuid"])
        projected_counts = [
            call.kwargs["resource_count"]
            for call in self.billing_client.check_entitlement.call_args_list
            if call.args[1] == "cashboxes"
        ]
        self.assertEqual(projected_counts, [1, 2])

    def test_duplicate_open_user_and_register_are_rejected(self):
        self._open(self.employee_one, self.register_one)

        same_user = self._client(self.employee_one).post(
            "/api/v1/cashboxes/open/",
            {"register_id": str(self.register_two.uuid), "initial_amount": "100.00"},
            format="json",
        )
        same_register = self._client(self.employee_two).post(
            "/api/v1/cashboxes/open/",
            {"register_id": str(self.register_one.uuid), "initial_amount": "100.00"},
            format="json",
        )

        self.assertEqual(same_user.status_code, 400)
        self.assertEqual(same_register.status_code, 400)
        self.assertEqual(Cashbox.objects.filter(tenant_id=self.tenant_id, status=Cashbox.Status.OPEN).count(), 1)

    def test_database_constraints_reject_duplicate_open_sessions(self):
        self._open(self.employee_one, self.register_one)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Cashbox.objects.create(
                tenant_id=self.tenant_id,
                register=self.register_two,
                opened_by=self.employee_one,
                initial_amount=Decimal("0.00"),
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Cashbox.objects.create(
                tenant_id=self.tenant_id,
                register=self.register_one,
                opened_by=self.employee_two,
                initial_amount=Decimal("0.00"),
            )

    def test_register_from_another_tenant_cannot_be_opened(self):
        response = self._client(self.employee_one).post(
            "/api/v1/cashboxes/open/",
            {"register_id": str(self.other_register.uuid), "initial_amount": "100.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Cashbox.objects.filter(tenant_id=self.tenant_id).exists())

    def test_close_is_user_scoped_and_admin_can_close_by_cashbox_id(self):
        first = self._open(self.employee_one, self.register_one)
        self._open(self.employee_two, self.register_two)

        forbidden = self._client(self.employee_two).post(
            "/api/v1/cashboxes/close/",
            {"cashbox_id": str(first.uuid), "final_amount": "100.00"},
            format="json",
        )
        admin_close = self._client(self.owner).post(
            "/api/v1/cashboxes/close/",
            {"cashbox_id": str(first.uuid), "final_amount": "100.00"},
            format="json",
        )

        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(admin_close.status_code, 200)
        first.refresh_from_db()
        self.assertEqual(first.closed_by, self.owner)
        self.assertEqual(self._client(self.employee_two).get("/api/v1/cashboxes/current/").status_code, 200)
        close_log = AuditLog.objects.get(
            entity=AuditLog.Entity.CASHBOX,
            entity_id=first.uuid,
            metadata__action="CLOSE",
        )
        self.assertEqual(close_log.metadata["cashbox_id"], str(first.uuid))
        self.assertEqual(close_log.metadata["register_id"], str(self.register_one.uuid))

    def test_owner_cannot_close_another_tenant_cashbox(self):
        other_user = User.objects.create_user(
            tenant_id=self.other_tenant.uuid,
            username="other-tenant-cashier",
            email="other-tenant-cashier@example.com",
            password="cashier1234",
            role=User.Role.EMPLOYEE,
        )
        other_cashbox = Cashbox.objects.create(
            tenant_id=self.other_tenant.uuid,
            register=self.other_register,
            opened_by=other_user,
            initial_amount=Decimal("100.00"),
        )

        response = self._client(self.owner).post(
            "/api/v1/cashboxes/close/",
            {"cashbox_id": str(other_cashbox.uuid), "final_amount": "100.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        other_cashbox.refresh_from_db()
        self.assertEqual(other_cashbox.status, Cashbox.Status.OPEN)

    def test_downgrade_denial_blocks_new_opening_but_never_close(self):
        cashbox = self._open(self.employee_one, self.register_one)
        entitlement_calls = self.billing_client.check_entitlement.call_count
        self.billing_client.check_entitlement.return_value = {
            "allowed": False,
            "reason": "resource_limit_exceeded",
            "limit": 1,
            "used": 2,
        }

        close_response = self._client(self.employee_one).post(
            "/api/v1/cashboxes/close/",
            {"final_amount": "100.00"},
            format="json",
        )
        blocked_open = self._client(self.employee_two).post(
            "/api/v1/cashboxes/open/",
            {"register_id": str(self.register_two.uuid), "initial_amount": "0.00"},
            format="json",
        )

        self.assertEqual(close_response.status_code, 200)
        self.assertEqual(blocked_open.status_code, 429)
        self.assertEqual(self.billing_client.check_entitlement.call_count, entitlement_calls + 1)
        cashbox.refresh_from_db()
        self.assertEqual(cashbox.status, Cashbox.Status.CLOSED)

    def test_historical_cashbox_without_register_remains_closable(self):
        historical = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.employee_one,
            initial_amount=Decimal("50.00"),
        )

        response = self._client(self.employee_one).post(
            "/api/v1/cashboxes/close/",
            {"final_amount": "50.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["register"])
        historical.refresh_from_db()
        self.assertEqual(historical.status, Cashbox.Status.CLOSED)

    def test_close_counts_cash_component_of_mixed_payments(self):
        cashbox = self._open(self.employee_one, self.register_one, initial_amount="100.00")
        Sale.objects.create(
            tenant_id=self.tenant_id,
            user=self.employee_one,
            cashbox=cashbox,
            total=Decimal("150.00"),
            payment_method=Sale.PaymentMethod.MIXED,
            payments=[
                {"method": Sale.PaymentMethod.CASH, "amount": "40.00"},
                {"method": Sale.PaymentMethod.CARD, "amount": "110.00"},
            ],
        )

        response = self._client(self.employee_one).post(
            "/api/v1/cashboxes/close/",
            {"final_amount": "140.00"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data["expected_amount"]), Decimal("140.00"))
        self.assertEqual(Decimal(response.data["difference"]), Decimal("0.00"))

    def _open(self, user, cash_register, initial_amount="100.00"):
        response = self._client(user).post(
            "/api/v1/cashboxes/open/",
            {"register_id": str(cash_register.uuid), "initial_amount": initial_amount},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return Cashbox.objects.get(uuid=response.data["uuid"])

    def _user(self, username, role):
        return User.objects.create_user(
            tenant_id=self.tenant_id,
            username=username,
            email=f"{username}@example.com",
            password="cashier1234",
            role=role,
        )

    @staticmethod
    def _client(user):
        client = APIClient()
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        access["tenant_id"] = str(user.tenant_id)
        access["role"] = user.role
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return client
