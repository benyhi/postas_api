import uuid
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tenants.models import Tenant, TenantConfig
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


class CreateTenantsCommandTests(TestCase):
    def test_creates_consecutive_tenants_from_empty_table(self):
        out = StringIO()

        call_command("create_tenants", 3, stdout=out)

        created_ids = list(Tenant.objects.order_by("uuid").values_list("uuid", flat=True))
        self.assertEqual(
            created_ids,
            [
                uuid.UUID(int=1),
                uuid.UUID(int=2),
                uuid.UUID(int=3),
            ],
        )
        self.assertIn("Created 3 tenant(s).", out.getvalue())

    def test_creates_after_highest_existing_tenant_uuid(self):
        Tenant.objects.create(uuid=uuid.UUID(int=7), name="Existing tenant")

        call_command("create_tenants", 2, name_prefix="Demo")

        tenants = list(Tenant.objects.order_by("uuid"))
        self.assertEqual([tenant.uuid for tenant in tenants], [uuid.UUID(int=7), uuid.UUID(int=8), uuid.UUID(int=9)])
        self.assertEqual(tenants[1].name, "Demo 8")
        self.assertEqual(tenants[2].name, "Demo 9")

    def test_dry_run_does_not_create_tenants(self):
        out = StringIO()

        call_command("create_tenants", 2, dry_run=True, stdout=out)

        self.assertEqual(Tenant.objects.count(), 0)
        self.assertIn("DRY-RUN 00000000000000000000000000000001", out.getvalue())

    def test_rejects_non_positive_count(self):
        with self.assertRaisesMessage(CommandError, "count must be greater than 0."):
            call_command("create_tenants", 0)

    def test_rejects_count_that_exceeds_uuid_range(self):
        max_uuid = uuid.UUID(int=(1 << 128) - 1)
        Tenant.objects.create(uuid=max_uuid, name="Last tenant")

        with self.assertRaisesMessage(CommandError, "count exceeds the remaining UUID range."):
            call_command("create_tenants", 1)

        self.assertEqual(Tenant.objects.count(), 1)

    def test_rejects_generated_names_longer_than_model_max_length(self):
        max_length = Tenant._meta.get_field("name").max_length

        with self.assertRaisesMessage(CommandError, f"generated tenant name exceeds {max_length} characters"):
            call_command("create_tenants", 1, name_prefix="T" * max_length)

        self.assertEqual(Tenant.objects.count(), 0)
