import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.arca.outbox import ArcaOutboxWorker


class Command(BaseCommand):
    help = "Procesa la outbox durable de facturacion ARCA."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("El worker ARCA outbox requiere PostgreSQL para claims concurrentes seguros.")
        worker = ArcaOutboxWorker()
        self.stdout.write("ARCA outbox worker started")
        while True:
            if worker.run_once() == 0:
                time.sleep(settings.ARCA_OUTBOX_POLL_SECONDS)
