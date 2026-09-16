import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.mercado_pago.worker import MercadoPagoWorker


class Command(BaseCommand):
    help = "Process durable Mercado Pago webhooks and pending order operations."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("run_mercado_pago_worker requires PostgreSQL for safe row claiming.")
        worker = MercadoPagoWorker()
        while True:
            processed = worker.run_once()
            if processed == 0:
                time.sleep(settings.MERCADO_PAGO_WORKER_POLL_SECONDS)
