import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.tenants.models import Tenant


MAX_UUID_INT = (1 << 128) - 1


class Command(BaseCommand):
    help = "Create tenants with consecutive UUIDs based on the highest existing Tenant.uuid."

    def add_arguments(self, parser):
        parser.add_argument(
            "count",
            type=int,
            help="Number of tenants to create.",
        )
        parser.add_argument(
            "--name-prefix",
            type=str,
            default="Tenant",
            help="Prefix used for generated tenant names. Default: Tenant",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the tenants that would be created without writing to the database.",
        )

    def handle(self, *args, **options):
        count = options["count"]
        if count <= 0:
            raise CommandError("count must be greater than 0.")

        last_int = self._highest_tenant_int()
        start = last_int + 1
        end = start + count - 1

        if end > MAX_UUID_INT:
            raise CommandError("count exceeds the remaining UUID range.")

        name_prefix = options["name_prefix"].strip()
        tenants = [
            Tenant(
                uuid=uuid.UUID(int=value),
                name=self._tenant_name(name_prefix, value),
            )
            for value in range(start, end + 1)
        ]
        self._validate_tenant_names(tenants)

        self.stdout.write(f"Current highest tenant UUID int: {last_int}")
        self.stdout.write(f"Creating tenant UUID ints: {start}..{end}")

        if options["dry_run"]:
            for tenant in tenants:
                self.stdout.write(f"  DRY-RUN {tenant.uuid.hex} name={tenant.name or '(empty)'}")
            self.stdout.write(self.style.WARNING("No tenants were created."))
            return

        with transaction.atomic():
            Tenant.objects.bulk_create(tenants)

        for tenant in tenants:
            self.stdout.write(self.style.SUCCESS(f"  CREATED {tenant.uuid.hex} name={tenant.name or '(empty)'}"))

        self.stdout.write(self.style.SUCCESS(f"Created {len(tenants)} tenant(s)."))

    @staticmethod
    def _highest_tenant_int():
        highest = 0
        for tenant_uuid in Tenant.objects.values_list("uuid", flat=True).iterator():
            highest = max(highest, tenant_uuid.int)
        return highest

    @staticmethod
    def _tenant_name(name_prefix, value):
        if not name_prefix:
            return ""
        return f"{name_prefix} {value}"

    @staticmethod
    def _validate_tenant_names(tenants):
        max_length = Tenant._meta.get_field("name").max_length
        if any(len(tenant.name) > max_length for tenant in tenants):
            raise CommandError(f"generated tenant name exceeds {max_length} characters; shorten --name-prefix.")
