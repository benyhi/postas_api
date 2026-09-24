import os
import uuid
from decimal import Decimal

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.cashbox.models import CashRegister
from apps.products.models import Category, Product
from apps.tenants.models import Tenant, TenantConfig
from apps.users.models import User


DEFAULT_TENANT_ID = uuid.UUID('00000000-0000-0000-0000-000000000001')
USERS = (
    ('owner', 'owner@preprod.postas.test', User.Role.OWNER, True, 'owner_password'),
    ('admin', 'admin@preprod.postas.test', User.Role.ADMIN, False, 'admin_password'),
    ('cajero', 'cajero@preprod.postas.test', User.Role.EMPLOYEE, False, 'cashier_password'),
)
PRODUCTS = (
    ('Bebidas', 'Agua mineral 500ml', '1200.00', '600.00', '40.000', '8.000', '779000000001'),
    ('Bebidas', 'Gaseosa cola 1.5L', '2600.00', '1500.00', '30.000', '6.000', '779000000002'),
    ('Almacen', 'Yerba mate 1kg', '4800.00', '3200.00', '25.000', '5.000', '779000000003'),
    ('Almacen', 'Arroz largo fino 1kg', '2100.00', '1350.00', '35.000', '7.000', '779000000004'),
    ('Limpieza', 'Detergente 750ml', '2300.00', '1400.00', '20.000', '4.000', '779000000005'),
)


class Command(BaseCommand):
    help = 'Crea datos minimos e idempotentes para el entorno de preproduccion.'

    def add_arguments(self, parser):
        parser.add_argument('--tenant-id', default=str(DEFAULT_TENANT_ID))
        parser.add_argument('--tenant-name', default='Postas Preproduccion')
        parser.add_argument('--owner-password', default=os.getenv('PREPROD_OWNER_PASSWORD'))
        parser.add_argument('--admin-password', default=os.getenv('PREPROD_ADMIN_PASSWORD'))
        parser.add_argument('--cashier-password', default=os.getenv('PREPROD_CASHIER_PASSWORD'))
        parser.add_argument(
            '--force-existing',
            action='store_true',
            help='Permite adoptar un tenant preexistente que no fue creado por este seed.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            tenant_id = uuid.UUID(options['tenant_id'])
        except (TypeError, ValueError) as exc:
            raise CommandError('tenant-id debe ser un UUID valido.') from exc

        passwords = {
            password_key: options.get(password_key)
            for *_, password_key in USERS
        }
        missing = [key for key, value in passwords.items() if not value]
        if missing:
            raise CommandError(
                'Defini PREPROD_OWNER_PASSWORD, PREPROD_ADMIN_PASSWORD y '
                'PREPROD_CASHIER_PASSWORD (o sus argumentos equivalentes).'
            )
        if len(set(passwords.values())) != len(passwords):
            raise CommandError('Cada rol debe usar una clave de preproduccion diferente.')
        for username, email, _role, _is_staff, password_key in USERS:
            candidate = User(username=username, email=email, tenant_id=tenant_id)
            try:
                validate_password(passwords[password_key], user=candidate)
            except ValidationError as exc:
                raise CommandError(
                    f'La clave de {username} no cumple la politica de seguridad: '
                    + ' '.join(exc.messages)
                ) from exc

        existing_tenant = Tenant.objects.filter(uuid=tenant_id).first()
        if existing_tenant is not None and not options['force_existing']:
            expected_identities = {(username, email) for username, email, *_ in USERS}
            current_identities = set(
                User.objects.all_with_inactive()
                .filter(tenant_id=tenant_id, username__in=[row[0] for row in USERS])
                .values_list('username', 'email')
            )
            if current_identities != expected_identities:
                raise CommandError(
                    'El tenant ya existe y no fue reconocido como seed de preproduccion. '
                    'Revisa el UUID o usa --force-existing de forma explicita.'
                )

        tenant, tenant_created = Tenant.objects.update_or_create(
            uuid=tenant_id,
            defaults={'name': options['tenant_name'], 'active': True},
        )
        TenantConfig.objects.update_or_create(
            tenant=tenant,
            defaults={
                'notification_email': 'owner@preprod.postas.test',
                'cashbox_email_notifications_enabled': False,
                'automatic_invoicing_enabled': False,
                'arca_environment': TenantConfig.ArcaEnvironment.DEVELOPMENT,
            },
        )

        created_users = 0
        for username, email, role, is_staff, password_key in USERS:
            user = User.objects.all_with_inactive().filter(
                tenant_id=tenant_id,
                username=username,
            ).first()
            if user is None:
                user = User(tenant_id=tenant_id, username=username)
                created_users += 1
            user.email = email
            user.role = role
            user.is_staff = is_staff
            user.active = True
            user.set_password(passwords[password_key])
            user.save()

        register, register_created = CashRegister.objects.update_or_create(
            tenant_id=tenant_id,
            name='Caja principal',
            defaults={'active': True},
        )

        categories = {}
        for category_name in sorted({row[0] for row in PRODUCTS}):
            category = Category.all_objects.filter(
                tenant_id=tenant_id,
                name=category_name,
            ).order_by('-active', 'uuid').first()
            if category is None:
                category = Category.all_objects.create(
                    tenant_id=tenant_id,
                    name=category_name,
                    active=True,
                )
            elif not category.active:
                category.active = True
                category.save(update_fields=['active'])
            categories[category_name] = category

        created_products = 0
        for category_name, name, price, cost, stock, min_stock, barcode in PRODUCTS:
            product = Product.all_objects.filter(
                tenant_id=tenant_id,
                name=name,
            ).order_by('-active', 'uuid').first()
            if product is None:
                product = Product(tenant_id=tenant_id, name=name)
                created_products += 1
            product.description = 'Producto de prueba para preproduccion.'
            product.price = Decimal(price)
            product.cost = Decimal(cost)
            product.unit = Product.Unit.U
            product.stock = Decimal(stock)
            product.min_stock = Decimal(min_stock)
            product.barcode = barcode
            product.category = categories[category_name]
            product.active = True
            product.save()

        self.stdout.write(self.style.SUCCESS('Seed de preproduccion aplicado.'))
        self.stdout.write(f'Tenant ID: {tenant_id}')
        self.stdout.write(f'Tenant: {"creado" if tenant_created else "actualizado"}')
        self.stdout.write(f'Usuarios nuevos: {created_users}; usuarios totales: {len(USERS)}')
        self.stdout.write(f'Terminal: {"creada" if register_created else "actualizada"} ({register.name})')
        self.stdout.write(f'Productos nuevos: {created_products}; productos totales: {len(PRODUCTS)}')
        self.stdout.write('Usuarios: owner, admin, cajero')
