import uuid

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tenants.models import TenantConfig
from apps.users.models import User


class TenantConfigEndpointTests(TestCase):
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
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._access_token(self.owner)}")

    def test_get_creates_config_for_current_tenant(self):
        response = self.client.get("/api/v1/tenant/config/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["tenant_id"], str(self.tenant_id))
        self.assertEqual(response.data["notification_email"], "")
        self.assertTrue(TenantConfig.objects.filter(tenant_id=self.tenant_id).exists())

    def test_patch_updates_notification_email(self):
        response = self.client.patch(
            "/api/v1/tenant/config/",
            {
                "notification_email": "alerts@example.com",
                "cashbox_email_notifications_enabled": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["notification_email"], "alerts@example.com")
        self.assertTrue(response.data["cashbox_email_notifications_enabled"])

    @staticmethod
    def _access_token(user):
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        access["tenant_id"] = str(user.tenant_id)
        access["role"] = user.role
        return str(access)
