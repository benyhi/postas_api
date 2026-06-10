import uuid
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.users.models import User


class UserBillingEnforcementTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.owner = User.objects.create_user(
            tenant_id=self.tenant_id,
            username="owner",
            email="owner@example.com",
            password="owner1234",
            role=User.Role.OWNER,
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access_token(self.owner)}")

    def test_create_user_blocks_when_resource_limit_is_exceeded(self):
        with patch("apps.platform_billing.enforcement.PlatformBillingClient") as client_class:
            client_class.return_value.check_entitlement.return_value = {
                "allowed": False,
                "reason": "resource_limit_exceeded",
                "message": "Limite de usuarios alcanzado.",
                "limit": 3,
                "used": 4,
                "remaining": 0,
            }
            response = self.client.post(
                "/api/v1/users/",
                {
                    "username": "cashier",
                    "email": "cashier@example.com",
                    "password": "cashier1234",
                    "role": User.Role.EMPLOYEE,
                },
                format="json",
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["code"], "resource_limit_exceeded")
        self.assertEqual(response.data["feature_key"], "users")
        self.assertFalse(User.objects.filter(tenant_id=self.tenant_id, username="cashier").exists())

    def test_create_user_blocks_cancelled_subscription_with_402(self):
        with patch("apps.platform_billing.enforcement.PlatformBillingClient") as client_class:
            client_class.return_value.check_entitlement.return_value = {
                "allowed": False,
                "reason": "subscription_cancelled",
                "message": "La suscripcion fue cancelada.",
            }
            response = self.client.post(
                "/api/v1/users/",
                {
                    "username": "admin",
                    "email": "admin@example.com",
                    "password": "admin1234",
                    "role": User.Role.ADMIN,
                },
                format="json",
            )

        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.data["code"], "subscription_cancelled")
        self.assertEqual(response.data["feature_key"], "users")

    @staticmethod
    def access_token(user):
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        access["tenant_id"] = str(user.tenant_id)
        access["role"] = user.role
        return str(access)
