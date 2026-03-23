"""
Reset the database: flush all data and re-run migrations.
Optionally re-seeds with test data.

Usage:
    python manage.py reset_db
    python manage.py reset_db --seed
    python manage.py reset_db --seed --sales 200
"""
from django.core.management.base import BaseCommand
from django.core.management import call_command


class Command(BaseCommand):
    help = "Flush all data, re-migrate, and optionally re-seed the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed",
            action="store_true",
            help="After reset, create test users and seed data",
        )
        parser.add_argument(
            "--sales",
            type=int,
            default=150,
            help="Number of sales to seed (only with --seed, default: 150)",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation prompt",
        )

    def handle(self, *args, **options):
        if not options["yes"]:
            confirm = input(
                "\n  ⚠ This will DELETE ALL DATA in the database.\n"
                "  Type 'yes' to confirm: "
            )
            if confirm.lower() != "yes":
                self.stdout.write(self.style.WARNING("  Aborted."))
                return

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write("  Flushing database...")
        call_command("flush", "--no-input", verbosity=0)
        self.stdout.write(self.style.SUCCESS("  Database flushed."))

        self.stdout.write("  Running migrations...")
        call_command("migrate", verbosity=0)
        self.stdout.write(self.style.SUCCESS("  Migrations applied."))

        if options["seed"]:
            self.stdout.write("  Creating test users...")
            call_command("create_test_users", verbosity=1)

            self.stdout.write("  Seeding data...")
            call_command("seed_data", sales=options["sales"], verbosity=1)

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(self.style.SUCCESS("  Database reset complete!"))
        self.stdout.write(f"{'='*60}\n")
