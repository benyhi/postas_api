import threading
import uuid
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.cashbox.models import Cashbox, CashRegister
from apps.tenants.models import Tenant
from apps.users.models import User


@skipUnless(
    connection.vendor == "postgresql",
    "select_for_update concurrency guarantees require PostgreSQL",
)
class CashboxPostgreSQLConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.tenant = Tenant.objects.create(uuid=uuid.uuid4(), name="Concurrent tenant")
        self.users = [self._user("concurrent-one"), self._user("concurrent-two")]
        self.registers = [
            CashRegister.objects.create(tenant_id=self.tenant.uuid, name="Concurrent 1"),
            CashRegister.objects.create(tenant_id=self.tenant.uuid, name="Concurrent 2"),
        ]

    @patch("apps.platform_billing.enforcement.PlatformBillingClient")
    def test_same_register_cannot_be_opened_concurrently(self, client_class):
        client_class.return_value.check_entitlement.return_value = {"allowed": True}
        statuses = self._open_concurrently([self.registers[0], self.registers[0]])

        self.assertEqual(statuses.count(201), 1)
        self.assertEqual(len(statuses), 2)
        self.assertIn(next(code for code in statuses if code != 201), {400, 409})
        self.assertEqual(
            Cashbox.objects.filter(
                tenant_id=self.tenant.uuid,
                register=self.registers[0],
                status=Cashbox.Status.OPEN,
            ).count(),
            1,
        )

    @patch("apps.platform_billing.enforcement.PlatformBillingClient")
    def test_same_user_cannot_open_two_registers_concurrently(self, client_class):
        client_class.return_value.check_entitlement.return_value = {"allowed": True}
        statuses = self._open_concurrently(
            self.registers,
            users=[self.users[0], self.users[0]],
        )

        self.assertEqual(statuses.count(201), 1)
        self.assertEqual(len(statuses), 2)
        self.assertIn(next(code for code in statuses if code != 201), {400, 409})
        self.assertEqual(
            Cashbox.objects.filter(
                tenant_id=self.tenant.uuid,
                opened_by=self.users[0],
                status=Cashbox.Status.OPEN,
            ).count(),
            1,
        )

    @patch("apps.platform_billing.enforcement.PlatformBillingClient")
    def test_plan_limit_uses_serialized_projected_open_count(self, client_class):
        def entitlement(*args, **kwargs):
            if kwargs["resource_count"] <= 1:
                return {"allowed": True}
            return {
                "allowed": False,
                "reason": "resource_limit_exceeded",
                "limit": 1,
                "used": kwargs["resource_count"],
                "remaining": 0,
            }

        client_class.return_value.check_entitlement.side_effect = entitlement
        statuses = self._open_concurrently(self.registers)

        self.assertEqual(sorted(statuses), [201, 429])
        self.assertEqual(
            Cashbox.objects.filter(
                tenant_id=self.tenant.uuid,
                status=Cashbox.Status.OPEN,
            ).count(),
            1,
        )

    def _open_concurrently(self, registers, users=None):
        barrier = threading.Barrier(2)
        statuses = []
        statuses_lock = threading.Lock()
        users = users or self.users

        def worker(user, cash_register):
            close_old_connections()
            try:
                client = self._client(user)
                barrier.wait(timeout=10)
                response = client.post(
                    "/api/v1/cashboxes/open/",
                    {"register_id": str(cash_register.uuid), "initial_amount": "0.00"},
                    format="json",
                )
                with statuses_lock:
                    statuses.append(response.status_code)
            finally:
                close_old_connections()

        threads = [
            threading.Thread(target=worker, args=(user, cash_register))
            for user, cash_register in zip(users, registers, strict=True)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        return statuses

    def _user(self, username):
        return User.objects.create_user(
            tenant_id=self.tenant.uuid,
            username=username,
            email=f"{username}@example.com",
            password="cashier1234",
            role=User.Role.EMPLOYEE,
        )

    @staticmethod
    def _client(user):
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token
        access["tenant_id"] = str(user.tenant_id)
        access["role"] = user.role
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return client
