import uuid
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.suppliers.models import Supplier
from apps.users.models import User


class SupplierBillingEnforcementTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.owner = User.objects.create_user(
            tenant_id=self.tenant_id,
            username="supplier_owner",
            email="supplier-owner@example.com",
            password="owner1234",
            role=User.Role.OWNER,
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token(self.owner)}")

    def test_create_supplier_blocks_when_resource_limit_is_exceeded(self):
        with patch("apps.platform_billing.enforcement.PlatformBillingClient") as client_class:
            client_class.return_value.check_entitlement.return_value = {
                "allowed": False,
                "reason": "resource_limit_exceeded",
                "message": "Limite de proveedores alcanzado.",
                "limit": 3,
                "used": 4,
                "remaining": 0,
            }
            response = self.client.post(
                "/api/v1/suppliers/",
                {"name": "Distribuidora Norte", "email": "ventas@norte.test"},
                format="json",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["code"], "resource_limit_exceeded")
        self.assertEqual(response.data["feature_key"], "suppliers")
        self.assertFalse(Supplier.objects.filter(tenant_id=self.tenant_id).exists())

    @staticmethod
    def access_token(user):
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        access["tenant_id"] = str(user.tenant_id)
        access["role"] = user.role
        return str(access)
