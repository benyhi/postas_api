import uuid
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.products.models import Category, Product
from apps.users.models import User


class ProductPermissionTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
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
        self.category = Category.objects.create(
            tenant_id=self.tenant_id,
            name="Bebidas",
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.employee)}")

    def test_employee_can_list_categories(self):
        response = self.client.get("/api/v1/categories/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_employee_can_retrieve_category(self):
        response = self.client.get(f"/api/v1/categories/{self.category.uuid}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["uuid"], str(self.category.uuid))

    def test_employee_cannot_create_category(self):
        response = self.client.post(
            "/api/v1/categories/",
            {"name": "Golosinas"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_employee_can_list_products(self):
        response = self.client.get("/api/v1/products/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_employee_can_retrieve_product(self):
        response = self.client.get(f"/api/v1/products/{self.product.uuid}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["uuid"], str(self.product.uuid))

    def test_employee_cannot_create_product(self):
        response = self.client.post(
            "/api/v1/products/",
            {
                "name": "Sprite 500ml",
                "price": "1500.00",
                "cost": "900.00",
                "stock": "10.000",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    @staticmethod
    def _access_token(user):
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        access["tenant_id"] = str(user.tenant_id)
        access["role"] = user.role
        return str(access)
