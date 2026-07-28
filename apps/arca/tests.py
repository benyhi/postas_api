import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.core.management import CommandError, call_command
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.arca.models import FiscalOutboxRequest
from apps.arca.outbox import ArcaOutboxWorker
from apps.cashbox.models import Cashbox
from apps.platform_billing.client import PlatformBillingError
from apps.products.models import Product
from apps.sales.models import Sale
from apps.tenants.models import Tenant, TenantConfig
from apps.users.models import User


def token_for(user):
    access = RefreshToken.for_user(user).access_token
    access["tenant_id"] = str(user.tenant_id)
    access["role"] = user.role
    return str(access)


class FakeOutboxClient:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def create_invoice(self, tenant_id, environment, payload, automatic=False):
        self.calls += 1
        if self.fail:
            raise PlatformBillingError("platform down", status_code=503)
        return {"id": 99, "status": "pending", "external_id": payload["external_id"]}


@override_settings(
    POSTAS_PLATFORM_REQUIRE_TLS=False,
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class ArcaApiTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.other_tenant_id = uuid.uuid4()
        self.tenant = Tenant.objects.create(uuid=self.tenant_id, name="Tenant")
        self.config = TenantConfig.objects.create(tenant=self.tenant)
        self.owner = User.objects.create_user(
            tenant_id=self.tenant_id,
            username="owner-arca",
            email="owner-arca@example.com",
            password="secret1234",
            role=User.Role.OWNER,
        )
        self.employee = User.objects.create_user(
            tenant_id=self.tenant_id,
            username="employee-arca",
            email="employee-arca@example.com",
            password="secret1234",
            role=User.Role.EMPLOYEE,
        )
        self.admin = User.objects.create_user(
            tenant_id=self.tenant_id,
            username="admin-arca",
            email="admin-arca@example.com",
            password="secret1234",
            role=User.Role.ADMIN,
        )
        self.product = Product.objects.create(
            tenant_id=self.tenant_id,
            name="Producto final",
            price=Decimal("121.00"),
            cost=Decimal("80.00"),
            stock=Decimal("10.000"),
        )
        self.cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.employee,
            initial_amount=Decimal("1000.00"),
        )
        self.client = APIClient()

    def authenticate(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_for(user)}")

    def test_outbox_worker_command_fails_closed_without_postgresql(self):
        with self.assertRaisesRegex(CommandError, "requiere PostgreSQL"):
            call_command("run_arca_outbox_worker")

    @patch("apps.arca.views.PlatformArcaClient")
    def test_only_owner_can_enable_automatic_invoicing(self, client_class):
        platform = client_class.return_value
        platform.check_entitlement.return_value = {"allowed": True}
        platform.get_profile.return_value = {
            "validation_status": "valid",
            "environment": "development",
            "concept": 1,
        }

        self.authenticate(self.employee)
        denied = self.client.put(
            "/api/v1/arca/configuration/",
            {"automatic_invoicing_enabled": True},
            format="json",
        )
        self.authenticate(self.owner)
        allowed = self.client.put(
            "/api/v1/arca/configuration/",
            {"automatic_invoicing_enabled": True, "arca_environment": "development"},
            format="json",
        )

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(allowed.status_code, 200)
        self.config.refresh_from_db()
        self.assertTrue(self.config.automatic_invoicing_enabled)

        disabled = self.client.put(
            "/api/v1/arca/configuration/",
            {"automatic_invoicing_enabled": False},
            format="json",
        )
        self.assertEqual(disabled.status_code, 200)
        self.config.refresh_from_db()
        self.assertFalse(self.config.automatic_invoicing_enabled)

    @patch("apps.arca.views.PlatformArcaClient")
    def test_automation_rejects_service_concept_profile(self, client_class):
        platform = client_class.return_value
        platform.check_entitlement.return_value = {"allowed": True}
        platform.get_profile.return_value = {
            "validation_status": "valid",
            "environment": "development",
            "concept": 2,
        }
        self.authenticate(self.owner)

        response = self.client.put(
            "/api/v1/arca/configuration/",
            {"automatic_invoicing_enabled": True},
            format="json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "automatic_invoicing_requires_products_concept")
        self.config.refresh_from_db()
        self.assertFalse(self.config.automatic_invoicing_enabled)

    @patch("apps.arca.views.PlatformArcaClient")
    def test_automation_requires_entitlement_and_a_validated_profile(self, client_class):
        platform = client_class.return_value
        self.authenticate(self.owner)

        platform.check_entitlement.return_value = {
            "allowed": False,
            "reason": "feature_not_enabled",
            "message": "El plan no habilita ARCA.",
        }
        denied = self.client.put(
            "/api/v1/arca/configuration/",
            {"automatic_invoicing_enabled": True},
            format="json",
        )

        self.assertEqual(denied.status_code, 403)
        self.config.refresh_from_db()
        self.assertFalse(self.config.automatic_invoicing_enabled)

        platform.check_entitlement.return_value = {"allowed": True}
        platform.get_profile.return_value = {"validation_status": "invalid"}
        invalid = self.client.put(
            "/api/v1/arca/configuration/",
            {"automatic_invoicing_enabled": True},
            format="json",
        )

        self.assertEqual(invalid.status_code, 409)
        self.config.refresh_from_db()
        self.assertFalse(self.config.automatic_invoicing_enabled)

    @patch("apps.arca.views.PlatformArcaClient")
    def test_configuration_response_never_echoes_submitted_secrets(self, client_class):
        platform = client_class.return_value
        platform.check_entitlement.return_value = {"allowed": True}
        platform.put_profile.return_value = {
            "tenant_id": str(self.tenant_id),
            "environment": "development",
            "arca_cuit": "20111111112",
            "validation_status": "pending",
        }
        platform.validate_profile.return_value = {"valid": True, "status": "valid"}
        self.authenticate(self.owner)

        response = self.client.put(
            "/api/v1/arca/configuration/",
            {
                "arca_cuit": "20111111112",
                "certificate": "certificate-secret",
                "private_key": "private-key-secret",
                "access_token": "access-token-secret",
                "point_of_sale": 1,
                "automatic_voucher_type": 6,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        serialized = str(response.data)
        self.assertNotIn("certificate-secret", serialized)
        self.assertNotIn("private-key-secret", serialized)
        self.assertNotIn("access-token-secret", serialized)

    @patch("apps.arca.views.PlatformArcaClient")
    def test_invoice_ignores_client_tenant_and_injects_jwt_tenant_actor(self, client_class):
        platform = client_class.return_value
        platform.create_invoice.return_value = {"id": 1, "status": "pending", "actor_id": str(self.employee.uuid)}
        self.authenticate(self.employee)

        response = self.client.post(
            "/api/v1/arca/invoices/",
            {
                "tenant_id": str(self.other_tenant_id),
                "environment": "production",
                "external_id": "manual-1",
                "items": [{"description": "Producto", "quantity": "1", "final_unit_price": "121.00"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 202)
        args = platform.create_invoice.call_args.args
        payload = args[2]
        self.assertEqual(str(args[0]), str(self.tenant_id))
        self.assertEqual(args[1], "development")
        self.assertEqual(payload["actor_id"], str(self.employee.uuid))
        self.assertNotIn("tenant_id", payload)

    @patch("apps.arca.views.PlatformArcaClient")
    def test_employee_cannot_follow_another_actors_invoice(self, client_class):
        client_class.return_value.get_by_external_id.return_value = {
            "id": 7,
            "status": "approved",
            "actor_id": str(uuid.uuid4()),
        }
        self.authenticate(self.employee)

        response = self.client.get("/api/v1/arca/invoices/by-external-id/private/")

        self.assertEqual(response.status_code, 404)

    @patch("apps.arca.views.PlatformArcaClient")
    def test_fiscal_number_queries_are_limited_to_admin_and_owner(self, client_class):
        platform = client_class.return_value
        platform.get_last_voucher.return_value = {
            "environment": "development",
            "point_of_sale": 1,
            "voucher_type": 6,
            "last_voucher_number": 10,
        }
        platform.get_fiscal.return_value = {"id": 7, "status": "approved"}
        fiscal_path = (
            "/api/v1/arca/invoices/fiscal/?environment=development&point_of_sale=1"
            "&voucher_type=6&voucher_number=10"
        )

        self.authenticate(self.employee)
        self.assertEqual(self.client.get("/api/v1/arca/invoices/last-voucher/").status_code, 403)
        self.assertEqual(self.client.get(fiscal_path).status_code, 403)

        self.authenticate(self.admin)
        self.assertEqual(self.client.get("/api/v1/arca/invoices/last-voucher/").status_code, 200)
        self.assertEqual(self.client.get(fiscal_path).status_code, 200)

    @patch("apps.platform_billing.enforcement.PlatformBillingClient")
    def test_sale_and_outbox_are_created_in_same_transaction_with_fixed_environment(self, billing_class):
        billing_class.return_value.check_and_consume.return_value = {"allowed": True, "recorded": True}
        self.config.automatic_invoicing_enabled = True
        self.config.arca_environment = "development"
        self.config.save()
        self.authenticate(self.employee)

        response = self.client.post(
            "/api/v1/sales/",
            {
                "payments": [{"method": "CASH", "amount": "121.00"}],
                "items": [{"product_id": str(self.product.uuid), "quantity": "1.000"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        request = FiscalOutboxRequest.objects.get(sale_id=response.data["uuid"])
        self.assertEqual(request.environment, "development")
        self.assertEqual(request.payload_snapshot["items"][0]["final_unit_price"], "121.00")
        self.assertEqual(response.data["invoice_status"], "pending")
        self.assertEqual(response.data["invoice_tracking_id"], request.external_id)

        self.config.arca_environment = "production"
        self.config.save()
        request.refresh_from_db()
        self.assertEqual(request.environment, "development")

    @patch("apps.platform_billing.enforcement.PlatformBillingClient")
    def test_sale_without_automation_has_no_outbox(self, billing_class):
        billing_class.return_value.check_and_consume.return_value = {"allowed": True, "recorded": True}
        self.authenticate(self.employee)

        response = self.client.post(
            "/api/v1/sales/",
            {
                "payments": [{"method": "CASH", "amount": "121.00"}],
                "items": [{"product_id": str(self.product.uuid), "quantity": "1.000"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["invoice_status"], "not_requested")
        self.assertFalse(FiscalOutboxRequest.objects.filter(sale_id=response.data["uuid"]).exists())

    @patch("apps.platform_billing.enforcement.PlatformBillingClient")
    def test_sale_and_outbox_roll_back_together_when_billing_does_not_confirm(self, billing_class):
        billing_class.return_value.check_and_consume.return_value = {
            "allowed": True,
            "recorded": False,
            "already_recorded": False,
        }
        self.config.automatic_invoicing_enabled = True
        self.config.save()
        self.authenticate(self.employee)

        response = self.client.post(
            "/api/v1/sales/",
            {
                "payments": [{"method": "CASH", "amount": "121.00"}],
                "items": [{"product_id": str(self.product.uuid), "quantity": "1.000"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(Sale.objects.filter(tenant_id=self.tenant_id).count(), 0)
        self.assertEqual(FiscalOutboxRequest.objects.filter(tenant_id=self.tenant_id).count(), 0)

    @patch("apps.platform_billing.enforcement.PlatformBillingClient")
    def test_platform_failure_does_not_revert_confirmed_sale_and_outbox_retries_idempotently(self, billing_class):
        billing_class.return_value.check_and_consume.return_value = {"allowed": True, "recorded": True}
        self.config.automatic_invoicing_enabled = True
        self.config.save()
        self.authenticate(self.employee)
        sale_response = self.client.post(
            "/api/v1/sales/",
            {
                "payments": [{"method": "CASH", "amount": "121.00"}],
                "items": [{"product_id": str(self.product.uuid), "quantity": "1.000"}],
            },
            format="json",
        )
        outbox = FiscalOutboxRequest.objects.get(sale_id=sale_response.data["uuid"])
        fake = FakeOutboxClient()
        fake.fail = True
        worker = ArcaOutboxWorker(client=fake, batch_size=1)

        self.assertEqual(worker.run_once(), 1)
        outbox.refresh_from_db()
        self.assertTrue(Sale.objects.filter(uuid=sale_response.data["uuid"]).exists())
        self.assertEqual(outbox.status, FiscalOutboxRequest.Status.RETRYING)

        fake.fail = False
        outbox.next_attempt_at = timezone.now()
        outbox.save(update_fields=["next_attempt_at"])
        self.assertEqual(worker.run_once(), 1)
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, FiscalOutboxRequest.Status.SENT)
        self.assertEqual(outbox.external_id, str(outbox.sale_id))
        self.assertEqual(fake.calls, 2)

    @patch("apps.platform_billing.enforcement.PlatformBillingClient")
    def test_outbox_retry_schedule_is_zero_one_ten_thirty_sixty_then_terminal(self, billing_class):
        billing_class.return_value.check_and_consume.return_value = {"allowed": True, "recorded": True}
        self.config.automatic_invoicing_enabled = True
        self.config.save()
        self.authenticate(self.employee)
        sale_response = self.client.post(
            "/api/v1/sales/",
            {
                "payments": [{"method": "CASH", "amount": "121.00"}],
                "items": [{"product_id": str(self.product.uuid), "quantity": "1.000"}],
            },
            format="json",
        )
        outbox = FiscalOutboxRequest.objects.get(sale_id=sale_response.data["uuid"])
        fake = FakeOutboxClient()
        fake.fail = True
        worker = ArcaOutboxWorker(client=fake, batch_size=1)
        fixed_now = timezone.now()

        self.assertLessEqual(outbox.next_attempt_at, fixed_now)
        with patch("apps.arca.outbox.timezone.now") as now:
            now.return_value = fixed_now
            for attempt, delay in enumerate((1, 10, 30, 60), start=1):
                self.assertEqual(worker.run_once(), 1)
                outbox.refresh_from_db()
                self.assertEqual(outbox.attempt_count, attempt)
                self.assertEqual(outbox.status, FiscalOutboxRequest.Status.RETRYING)
                self.assertEqual(outbox.next_attempt_at, now.return_value + timedelta(minutes=delay))
                now.return_value = outbox.next_attempt_at

            self.assertEqual(worker.run_once(), 1)

        outbox.refresh_from_db()
        self.assertEqual(outbox.attempt_count, 5)
        self.assertEqual(outbox.status, FiscalOutboxRequest.Status.FAILED)
        self.assertIsNone(outbox.next_attempt_at)
