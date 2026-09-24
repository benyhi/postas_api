import uuid
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.cashbox.models import CashRegister
from apps.products.models import Category, Product
from apps.tenants.models import Tenant, TenantConfig
from apps.users.management.commands.seed_preprod import DEFAULT_TENANT_ID, PRODUCTS, USERS
from apps.users.models import User


class SeedPreprodCommandTests(TestCase):
    tenant_id = uuid.UUID('00000000-0000-0000-0000-000000000001')

    passwords = {
        'owner_password': 'Owner-Preprod!7391',
        'admin_password': 'Admin-Preprod!8462',
        'cashier_password': 'Cashier-Preprod!9513',
    }

    def test_seed_is_idempotent_and_creates_required_data(self):
        first_stdout = StringIO()
        call_command(
            'seed_preprod',
            tenant_id=str(self.tenant_id),
            **self.passwords,
            stdout=first_stdout,
        )
        first_user_ids = set(
            User.objects.filter(tenant_id=self.tenant_id).values_list('uuid', flat=True)
        )
        first_product_ids = set(
            Product.all_objects.filter(tenant_id=self.tenant_id).values_list('uuid', flat=True)
        )

        second_stdout = StringIO()
        call_command(
            'seed_preprod',
            tenant_id=str(self.tenant_id),
            **self.passwords,
            stdout=second_stdout,
        )

        self.assertEqual(DEFAULT_TENANT_ID, self.tenant_id)
        self.assertEqual(Tenant.objects.filter(uuid=self.tenant_id).count(), 1)
        self.assertEqual(TenantConfig.objects.filter(tenant_id=self.tenant_id).count(), 1)
        self.assertEqual(User.objects.filter(tenant_id=self.tenant_id).count(), 3)
        self.assertEqual(CashRegister.objects.filter(tenant_id=self.tenant_id).count(), 1)
        self.assertEqual(Category.objects.filter(tenant_id=self.tenant_id).count(), 3)
        self.assertEqual(Product.objects.filter(tenant_id=self.tenant_id).count(), 5)
        self.assertEqual(
            set(User.objects.filter(tenant_id=self.tenant_id).values_list('uuid', flat=True)),
            first_user_ids,
        )
        self.assertEqual(
            set(
                Product.all_objects.filter(tenant_id=self.tenant_id).values_list(
                    'uuid', flat=True
                )
            ),
            first_product_ids,
        )

        expected_users = {
            username: (email, role, is_staff, password_key)
            for username, email, role, is_staff, password_key in USERS
        }
        users = User.objects.filter(tenant_id=self.tenant_id)
        self.assertEqual(set(users.values_list('username', flat=True)), set(expected_users))
        for user in users:
            with self.subTest(username=user.username):
                self.assertEqual(
                    (user.email, user.role, user.is_staff),
                    expected_users[user.username][:3],
                )
                self.assertTrue(user.active)
                password = self.passwords[expected_users[user.username][3]]
                self.assertTrue(user.check_password(password))
                self.assertNotEqual(user.password, password)

        config = TenantConfig.objects.get(tenant_id=self.tenant_id)
        self.assertFalse(config.cashbox_email_notifications_enabled)
        self.assertFalse(config.automatic_invoicing_enabled)
        self.assertEqual(config.arca_environment, TenantConfig.ArcaEnvironment.DEVELOPMENT)
        self.assertEqual(
            set(Product.objects.filter(tenant_id=self.tenant_id).values_list('name', flat=True)),
            {row[1] for row in PRODUCTS},
        )
        for password in self.passwords.values():
            self.assertNotIn(password, first_stdout.getvalue())
            self.assertNotIn(password, second_stdout.getvalue())

    def test_password_is_required(self):
        with self.assertRaisesMessage(CommandError, 'PREPROD_OWNER_PASSWORD'):
            call_command(
                'seed_preprod',
                tenant_id=str(self.tenant_id),
                stdout=StringIO(),
            )

    def test_rejects_invalid_tenant_id_and_short_password_without_creating_data(self):
        with self.assertRaisesMessage(CommandError, 'tenant-id debe ser un UUID valido'):
            call_command(
                'seed_preprod',
                tenant_id='not-a-uuid',
                **self.passwords,
                stdout=StringIO(),
            )

        weak_passwords = {**self.passwords, 'owner_password': '1234567890123456'}
        with self.assertRaisesMessage(CommandError, 'politica de seguridad'):
            call_command(
                'seed_preprod',
                tenant_id=str(self.tenant_id),
                **weak_passwords,
                stdout=StringIO(),
            )

        self.assertFalse(Tenant.objects.filter(uuid=self.tenant_id).exists())
        self.assertFalse(User.objects.filter(tenant_id=self.tenant_id).exists())

    def test_rejects_shared_passwords_and_unrecognized_existing_tenant(self):
        shared_passwords = {
            key: 'Shared-Preprod!7391' for key in self.passwords
        }
        with self.assertRaisesMessage(CommandError, 'Cada rol'):
            call_command(
                'seed_preprod',
                tenant_id=str(self.tenant_id),
                **shared_passwords,
                stdout=StringIO(),
            )

        Tenant.objects.create(uuid=self.tenant_id, name='Tenant existente')
        with self.assertRaisesMessage(CommandError, 'no fue reconocido'):
            call_command(
                'seed_preprod',
                tenant_id=str(self.tenant_id),
                **self.passwords,
                stdout=StringIO(),
            )

        self.assertEqual(Tenant.objects.get(uuid=self.tenant_id).name, 'Tenant existente')
        self.assertFalse(User.objects.filter(tenant_id=self.tenant_id).exists())
