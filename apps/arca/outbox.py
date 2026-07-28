from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.arca.client import PlatformArcaClient
from apps.arca.models import FiscalOutboxRequest
from apps.platform_billing.client import PlatformBillingError
from apps.tenants.models import TenantConfig


RETRY_DELAYS_MINUTES = (0, 1, 10, 30, 60)


def create_sale_fiscal_request(sale, user):
    config = TenantConfig.objects.filter(tenant_id=sale.tenant_id).first()
    if config is None or not config.automatic_invoicing_enabled:
        return None
    snapshot = {
        "external_id": str(sale.uuid),
        "sale_id": str(sale.uuid),
        "actor_id": str(user.uuid),
        "actor_role": user.role,
        "receiver": {"doc_type": 99, "doc_number": "0", "iva_condition_id": 5},
        "invoice_date": sale.created_at.date().isoformat(),
        "items": [
            {
                "description": detail.product.name,
                "quantity": str(detail.quantity),
                "final_unit_price": str(detail.price),
            }
            for detail in sale.details.select_related("product").all()
        ],
    }
    return FiscalOutboxRequest.objects.create(
        tenant_id=sale.tenant_id,
        sale=sale,
        created_by=user,
        environment=config.arca_environment,
        external_id=str(sale.uuid),
        payload_snapshot=snapshot,
        next_attempt_at=timezone.now(),
    )


class ArcaOutboxWorker:
    def __init__(self, *, client=None, batch_size=None):
        self.client = client or PlatformArcaClient()
        self.batch_size = batch_size or settings.ARCA_OUTBOX_BATCH_SIZE

    def run_once(self):
        processed = 0
        for _ in range(self.batch_size):
            request_id = self._claim_one()
            if request_id is None:
                break
            self._deliver(request_id)
            processed += 1
        return processed

    @transaction.atomic
    def _claim_one(self):
        stale_before = timezone.now() - timedelta(minutes=5)
        queryset = FiscalOutboxRequest.objects.filter(
            status__in=[
                FiscalOutboxRequest.Status.PENDING,
                FiscalOutboxRequest.Status.RETRYING,
                FiscalOutboxRequest.Status.SENDING,
            ]
        ).filter(next_attempt_at__lte=timezone.now())
        queryset = queryset.exclude(status=FiscalOutboxRequest.Status.SENDING, locked_at__gt=stale_before)
        if connection.features.has_select_for_update_skip_locked:
            queryset = queryset.select_for_update(skip_locked=True)
        else:
            queryset = queryset.select_for_update()
        record = queryset.order_by("next_attempt_at", "created_at").first()
        if record is None:
            return None
        record.status = FiscalOutboxRequest.Status.SENDING
        record.attempt_count += 1
        record.locked_at = timezone.now()
        record.save(update_fields=["status", "attempt_count", "locked_at", "updated_at"])
        return record.uuid

    def _deliver(self, request_id):
        record = FiscalOutboxRequest.objects.get(uuid=request_id)
        try:
            response = self.client.create_invoice(
                record.tenant_id,
                record.environment,
                record.payload_snapshot,
                automatic=True,
            )
        except PlatformBillingError as exc:
            self._record_failure(record, "platform_unavailable", exc.message)
            return
        record.status = FiscalOutboxRequest.Status.SENT
        record.invoice_status = str(response.get("status") or "pending")
        record.platform_invoice_id = response.get("id")
        record.next_attempt_at = None
        record.locked_at = None
        record.last_error_code = ""
        record.last_error_message = ""
        record.save()

    @staticmethod
    def _record_failure(record, code, message):
        if record.attempt_count >= len(RETRY_DELAYS_MINUTES):
            record.status = FiscalOutboxRequest.Status.FAILED
            record.next_attempt_at = None
        else:
            record.status = FiscalOutboxRequest.Status.RETRYING
            record.next_attempt_at = timezone.now() + timedelta(
                minutes=RETRY_DELAYS_MINUTES[record.attempt_count]
            )
        record.invoice_status = "platform_pending"
        record.locked_at = None
        record.last_error_code = code
        record.last_error_message = str(message)[:1000]
        record.save()
