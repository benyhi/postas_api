import uuid
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.cashbox.models import Cashbox
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

    def test_employee_can_view_open_cashbox_summary_by_id(self):
        cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.owner,
            initial_amount=Decimal("1000.00"),
        )

        response = self.client.get(f"/api/v1/reports/cashbox/summary/?cashbox_id={cashbox.uuid}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["cashbox_uuid"], cashbox.uuid)
        self.assertEqual(response.data["status"], Cashbox.Status.OPEN)

    def test_employee_can_view_current_open_cashbox_summary_without_id(self):
        cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.owner,
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

    @staticmethod
    def _access_token(user):
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        access["tenant_id"] = str(user.tenant_id)
        access["role"] = user.role
        return str(access)
