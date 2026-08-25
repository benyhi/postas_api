import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.cashbox.models import Cashbox, CashRegister
from apps.sales.models import Sale
from apps.users.models import User


class CashboxSummaryReportPermissionTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
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
        self.other_employee = User.objects.create_user(
            tenant_id=self.tenant_id,
            username="other",
            email="other@example.com",
            password="other1234",
            role=User.Role.EMPLOYEE,
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.employee)}")
        self.billing_patcher = patch("apps.platform_billing.enforcement.PlatformBillingClient")
        self.billing_client_class = self.billing_patcher.start()
        self.addCleanup(self.billing_patcher.stop)
        self.billing_client = self.billing_client_class.return_value
        self.billing_client.check_entitlement.return_value = {"allowed": True}

    def test_employee_can_view_open_cashbox_summary_by_id(self):
        cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.employee,
            initial_amount=Decimal("1000.00"),
        )

        response = self.client.get(f"/api/v1/reports/cashbox/summary/?cashbox_id={cashbox.uuid}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["cashbox_uuid"], cashbox.uuid)
        self.assertEqual(response.data["status"], Cashbox.Status.OPEN)

    def test_employee_can_view_current_open_cashbox_summary_without_id(self):
        cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.employee,
            initial_amount=Decimal("1000.00"),
        )

        response = self.client.get("/api/v1/reports/cashbox/summary/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["cashbox_uuid"], cashbox.uuid)

    def test_employee_cannot_view_closed_cashbox_summary_from_other_user(self):
        cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.other_employee,
            closed_by=self.owner,
            opened_at=timezone.now(),
            closed_at=timezone.now(),
            initial_amount=Decimal("1000.00"),
            final_amount=Decimal("1000.00"),
            expected_amount=Decimal("1000.00"),
            difference=Decimal("0.00"),
            status=Cashbox.Status.CLOSED,
        )

        response = self.client.get(f"/api/v1/reports/cashbox/summary/?cashbox_id={cashbox.uuid}")

        self.assertEqual(response.status_code, 403)

    def test_cashbox_summary_rejects_invalid_cashbox_id(self):
        response = self.client.get("/api/v1/reports/cashbox/summary/?cashbox_id=invalid")

        self.assertEqual(response.status_code, 400)

    def test_daily_sales_report_scopes_by_tenant_register_session_and_operator(self):
        register_one = CashRegister.objects.create(
            tenant_id=self.tenant_id,
            name="Report terminal 1",
        )
        register_two = CashRegister.objects.create(
            tenant_id=self.tenant_id,
            name="Report terminal 2",
        )
        cashbox_one = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            register=register_one,
            opened_by=self.employee,
            initial_amount=Decimal("0.00"),
            status=Cashbox.Status.CLOSED,
        )
        cashbox_two = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            register=register_two,
            opened_by=self.other_employee,
            initial_amount=Decimal("0.00"),
            status=Cashbox.Status.CLOSED,
        )
        Sale.objects.create(
            tenant_id=self.tenant_id,
            user=self.employee,
            cashbox=cashbox_one,
            total=Decimal("100.00"),
            payment_method=Sale.PaymentMethod.CASH,
        )
        Sale.objects.create(
            tenant_id=self.tenant_id,
            user=self.other_employee,
            cashbox=cashbox_two,
            total=Decimal("200.00"),
            payment_method=Sale.PaymentMethod.CARD,
        )

        other_tenant_id = uuid.uuid4()
        other_owner = User.objects.create_user(
            tenant_id=other_tenant_id,
            username="other-tenant-owner",
            email="other-tenant-owner@example.com",
            password="owner1234",
            role=User.Role.OWNER,
        )
        other_register = CashRegister.objects.create(
            tenant_id=other_tenant_id,
            name="Other tenant terminal",
        )
        other_cashbox = Cashbox.objects.create(
            tenant_id=other_tenant_id,
            register=other_register,
            opened_by=other_owner,
            initial_amount=Decimal("0.00"),
            status=Cashbox.Status.CLOSED,
        )
        Sale.objects.create(
            tenant_id=other_tenant_id,
            user=other_owner,
            cashbox=other_cashbox,
            total=Decimal("999.00"),
            payment_method=Sale.PaymentMethod.CASH,
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.owner)}")

        unfiltered = self.client.get("/api/v1/reports/sales/daily/")
        by_register = self.client.get(
            f"/api/v1/reports/sales/daily/?register_id={register_one.uuid}"
        )
        by_cashbox = self.client.get(
            f"/api/v1/reports/sales/daily/?cashbox_id={cashbox_two.uuid}"
        )
        by_operator = self.client.get(
            f"/api/v1/reports/sales/daily/?user_id={self.employee.uuid}"
        )

        self.assertEqual(unfiltered.status_code, 200)
        self.assertEqual(unfiltered.data["sale_count"], 2)
        self.assertEqual(Decimal(unfiltered.data["total_sold"]), Decimal("300.00"))
        self.assertEqual(by_register.data["sale_count"], 1)
        self.assertEqual(Decimal(by_register.data["total_sold"]), Decimal("100.00"))
        self.assertEqual(by_cashbox.data["sale_count"], 1)
        self.assertEqual(Decimal(by_cashbox.data["total_sold"]), Decimal("200.00"))
        self.assertEqual(by_operator.data["sale_count"], 1)
        self.assertEqual(Decimal(by_operator.data["total_sold"]), Decimal("100.00"))

    def test_advanced_report_blocks_when_feature_is_not_enabled(self):
        self.billing_client.check_entitlement.return_value = {
            "allowed": False,
            "reason": "feature_not_enabled",
            "message": "Reportes avanzados no habilitados.",
        }
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.owner)}")

        response = self.client.get("/api/v1/reports/products/top/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "feature_not_enabled")
        self.assertEqual(response.data["feature_key"], "advanced_reports")

    def test_cashbox_summary_blocks_when_basic_reports_feature_is_not_enabled(self):
        Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.owner,
            initial_amount=Decimal("1000.00"),
        )
        self.billing_client.check_entitlement.return_value = {
            "allowed": False,
            "reason": "feature_not_enabled",
            "message": "Reportes basicos no habilitados.",
        }

        response = self.client.get("/api/v1/reports/cashbox/summary/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "feature_not_enabled")
        self.assertEqual(response.data["feature_key"], "basic_reports")

    @staticmethod
    def _access_token(user):
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        access["tenant_id"] = str(user.tenant_id)
        access["role"] = user.role
        return str(access)
