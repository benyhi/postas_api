"""
Create a test tenant with Owner, Admin, and Employee users.

Usage:
    python manage.py create_test_users
    python manage.py create_test_users --tenant-id <uuid>
"""
import uuid

from django.core.management.base import BaseCommand

from apps.users.models import User


TEST_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

USERS = [
    {
        "username": "owner",
        "email": "owner@postas.test",
        "password": "owner1234",
        "role": "OWNER",
        "is_staff": True,
    },
    {
        "username": "admin",
        "email": "admin@postas.test",
        "password": "admin1234",
        "role": "ADMIN",
    },
    {
        "username": "empleado1",
        "email": "empleado1@postas.test",
        "password": "empleado1234",
        "role": "EMPLOYEE",
    },
    {
        "username": "empleado2",
        "email": "empleado2@postas.test",
        "password": "empleado1234",
        "role": "EMPLOYEE",
    },
]


class Command(BaseCommand):
    help = "Create a test tenant with Owner, Admin, and Employee users"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-id",
            type=str,
            default=str(TEST_TENANT_ID),
            help="UUID for the test tenant (default: 00000000-...0001)",
        )

    def handle(self, *args, **options):
        tenant_id = uuid.UUID(options["tenant_id"])

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"  POSTAS - Test Users Setup")
        self.stdout.write(f"  Tenant ID: {tenant_id}")
        self.stdout.write(f"{'='*60}\n")

        for data in USERS:
            user, created = User.objects.all_with_inactive().get_or_create(
                tenant_id=tenant_id,
                username=data["username"],
                defaults={
                    "email": data["email"],
                    "role": data["role"],
                    "is_staff": data.get("is_staff", False),
                },
            )
            if created:
                user.set_password(data["password"])
                user.save(update_fields=["password"])
                status = self.style.SUCCESS("CREATED")
            else:
                status = self.style.WARNING("EXISTS")

            self.stdout.write(
                f"  [{status}] {data['role']:<10} "
                f"user={data['username']:<12} "
                f"pass={data['password']:<15} "
                f"uuid={user.uuid}"
            )

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(self.style.SUCCESS("  Login example:"))
        self.stdout.write(f'  POST /api/v1/auth/login/')
        self.stdout.write(f'  {{"tenant_id": "{tenant_id}",')
        self.stdout.write(f'   "username": "owner",')
        self.stdout.write(f'   "password": "owner1234"}}')
        self.stdout.write(f"{'='*60}\n")
