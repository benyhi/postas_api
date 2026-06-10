import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.cashbox.models import Cashbox
from apps.products.models import Product
from apps.sales.models import Sale, SaleDetail
from apps.users.models import User


class SaleEmployeePermissionTests(TestCase):
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
            username="employee",
            email="employee@example.com",
            password="employee1234",
            role=User.Role.EMPLOYEE,
        )
        self.product = Product.objects.create(
            tenant_id=self.tenant_id,
            name="Coca Cola 500ml",
            price=Decimal("1500.00"),
            cost=Decimal("900.00"),
            stock=Decimal("10.000"),
        )
        self.open_cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.employee,
            initial_amount=Decimal("1000.00"),
        )
        self.closed_cashbox = Cashbox.objects.create(
            tenant_id=self.tenant_id,
            opened_by=self.employee,
            closed_by=self.owner,
            initial_amount=Decimal("1000.00"),
            final_amount=Decimal("1000.00"),
            expected_amount=Decimal("1000.00"),
            difference=Decimal("0.00"),
            status=Cashbox.Status.CLOSED,
        )
        self.current_sale = self._create_sale(self.open_cashbox, Decimal("1500.00"))
        self.closed_cashbox_sale = self._create_sale(self.closed_cashbox, Decimal("2500.00"))
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.employee)}")
        self.billing_patcher = patch("apps.platform_billing.enforcement.PlatformBillingClient")
        self.billing_client_class = self.billing_patcher.start()
        self.addCleanup(self.billing_patcher.stop)
        self.billing_client = self.billing_client_class.return_value
        self.billing_client.check_and_consume.return_value = {"allowed": True, "recorded": True}

    def test_employee_can_create_sale(self):
        response = self.client.post(
            "/api/v1/sales/",
            {
                "payments": [{"method": Sale.PaymentMethod.CASH, "amount": "1500.00"}],
                "items": [{"product_id": str(self.product.uuid), "quantity": "1.000"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["cashbox"], self.open_cashbox.uuid)
        self.assertEqual(response.data["user"], self.employee.uuid)
        self.billing_client.check_and_consume.assert_called_once()
        self.assertEqual(
            self.billing_client.check_and_consume.call_args.args[1],
            "pos_sales",
        )
        self.assertTrue(
            self.billing_client.check_and_consume.call_args.kwargs["idempotency_key"].startswith("sale:")
        )

    def test_sale_rolls_back_when_usage_is_not_confirmed(self):
        self.billing_client.check_and_consume.return_value = {
            "allowed": True,
            "recorded": False,
            "already_recorded": False,
        }
        sale_count = Sale.objects.filter(tenant_id=self.tenant_id).count()
        initial_stock = self.product.stock

        response = self.client.post(
            "/api/v1/sales/",
            {
                "payments": [{"method": Sale.PaymentMethod.CASH, "amount": "1500.00"}],
                "items": [{"product_id": str(self.product.uuid), "quantity": "1.000"}],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], "billing_service_unavailable")
        self.assertEqual(Sale.objects.filter(tenant_id=self.tenant_id).count(), sale_count)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, initial_stock)

    def test_employee_can_list_only_current_cashbox_sales(self):
        response = self.client.get("/api/v1/sales/")

        self.assertEqual(response.status_code, 200)
        sale_ids = {item["uuid"] for item in response.data["results"]}
        self.assertIn(str(self.current_sale.uuid), sale_ids)
        self.assertNotIn(str(self.closed_cashbox_sale.uuid), sale_ids)

    def test_employee_can_retrieve_current_cashbox_sale(self):
        response = self.client.get(f"/api/v1/sales/{self.current_sale.uuid}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["uuid"], str(self.current_sale.uuid))

    def test_employee_cannot_retrieve_sale_from_closed_cashbox(self):
        response = self.client.get(f"/api/v1/sales/{self.closed_cashbox_sale.uuid}/")

        self.assertEqual(response.status_code, 404)

    def test_owner_can_list_all_sales(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.owner)}")

        response = self.client.get("/api/v1/sales/")

        self.assertEqual(response.status_code, 200)
        sale_ids = {item["uuid"] for item in response.data["results"]}
        self.assertIn(str(self.current_sale.uuid), sale_ids)
        self.assertIn(str(self.closed_cashbox_sale.uuid), sale_ids)

    def _create_sale(self, cashbox, total):
        sale = Sale.objects.create(
            tenant_id=self.tenant_id,
            user=self.employee,
            cashbox=cashbox,
            total=total,
            payment_method=Sale.PaymentMethod.CASH,
        )
        SaleDetail.objects.create(
            sale=sale,
            product=self.product,
            quantity=Decimal("1.000"),
            price=total,
            subtotal=total,
        )
        return sale

    @staticmethod
    def _access_token(user):
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        access["tenant_id"] = str(user.tenant_id)
        access["role"] = user.role
        return str(access)
