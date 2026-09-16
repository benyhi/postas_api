from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.mercado_pago.client import PlatformMercadoPagoClient
from apps.mercado_pago.models import (
    MercadoPagoBillingRelease,
    MercadoPagoOrder,
    MercadoPagoWebhookInbox,
)
from apps.mercado_pago.services import attempt_create_order, reconcile_order
from apps.platform_billing.client import PlatformBillingError
from apps.platform_billing.enforcement import (
    BillingEnforcementError,
    release_billing_reservation,
)


class MercadoPagoWorker:
    def __init__(self, *, client=None, batch_size=None):
        self.client = client or PlatformMercadoPagoClient()
        self.batch_size = batch_size or settings.MERCADO_PAGO_WORKER_BATCH_SIZE

    def run_once(self):
        processed = 0
        for _ in range(self.batch_size):
            release_id = self._claim_billing_release()
            if release_id is None:
                break
            self._process_billing_release(release_id)
            processed += 1
        for _ in range(self.batch_size):
            if processed >= self.batch_size:
                break
            inbox_id = self._claim_inbox()
            if inbox_id is None:
                break
            self._process_inbox(inbox_id)
            processed += 1
        for _ in range(max(0, self.batch_size - processed)):
            order_id = self._claim_order()
            if order_id is None:
                break
            self._process_order(order_id)
            processed += 1
        return processed

    @transaction.atomic
    def _claim_billing_release(self):
        now = timezone.now()
        stale = now - timedelta(seconds=settings.MERCADO_PAGO_WORKER_STALE_SECONDS)
        queryset = MercadoPagoBillingRelease.objects.filter(
            next_attempt_at__lte=now,
        ).filter(Q(locked_at__isnull=True) | Q(locked_at__lte=stale))
        queryset = (
            queryset.select_for_update(skip_locked=True)
            if connection.features.has_select_for_update_skip_locked
            else queryset.select_for_update()
        )
        task = queryset.order_by("next_attempt_at", "created_at").first()
        if task is None:
            return None
        task.locked_at = now
        task.attempt_count += 1
        task.save(update_fields=["locked_at", "attempt_count", "updated_at"])
        return task.uuid

    def _process_billing_release(self, release_id):
        task = MercadoPagoBillingRelease.objects.get(uuid=release_id)
        if MercadoPagoOrder.objects.filter(
            tenant_id=task.tenant_id,
            billing_reservation_key=task.idempotency_key,
        ).exists():
            task.delete()
            return
        try:
            release_billing_reservation(
                task.tenant_id,
                idempotency_key=task.idempotency_key,
                client=self.client,
            )
        except BillingEnforcementError as exc:
            task.locked_at = None
            task.next_attempt_at = timezone.now() + timedelta(
                seconds=min(300, 5 * (2 ** min(task.attempt_count, 6)))
            )
            task.last_error = str(exc.detail)[:1000]
            task.save(
                update_fields=[
                    "locked_at",
                    "next_attempt_at",
                    "last_error",
                    "updated_at",
                ]
            )
            return
        task.delete()

    @transaction.atomic
    def _claim_inbox(self):
        now = timezone.now()
        stale = now - timedelta(seconds=settings.MERCADO_PAGO_WORKER_STALE_SECONDS)
        queryset = MercadoPagoWebhookInbox.objects.filter(
            status__in=[
                MercadoPagoWebhookInbox.Status.PENDING,
                MercadoPagoWebhookInbox.Status.RETRYING,
                MercadoPagoWebhookInbox.Status.PROCESSING,
            ],
        ).filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        queryset = queryset.exclude(
            status=MercadoPagoWebhookInbox.Status.PROCESSING, locked_at__gt=stale,
        )
        queryset = queryset.select_for_update(skip_locked=True) if connection.features.has_select_for_update_skip_locked else queryset.select_for_update()
        record = queryset.order_by("created_at").first()
        if not record:
            return None
        record.status = MercadoPagoWebhookInbox.Status.PROCESSING
        record.attempt_count += 1
        record.locked_at = now
        record.save(update_fields=["status", "attempt_count", "locked_at", "updated_at"])
        return record.uuid

    def _process_inbox(self, inbox_id):
        record = MercadoPagoWebhookInbox.objects.get(uuid=inbox_id)
        if record.topic and record.topic not in {"order", "orders"}:
            self._finish_inbox(record, MercadoPagoWebhookInbox.Status.IGNORED)
            return
        order = MercadoPagoOrder.objects.filter(external_order_id=record.data_id).first()
        if order is None:
            record.status = MercadoPagoWebhookInbox.Status.RETRYING
            record.next_attempt_at = timezone.now() + timedelta(
                seconds=min(300, 5 * (2 ** min(record.attempt_count, 6)))
            )
            record.locked_at = None
            record.last_error_code = "order_not_linked"
            record.last_error_message = "The local order is not linked yet."
            record.save()
            return
        try:
            reconciled = reconcile_order(order.uuid, client=self.client)
        except BillingEnforcementError as exc:
            record.status = MercadoPagoWebhookInbox.Status.RETRYING
            record.next_attempt_at = timezone.now() + timedelta(
                seconds=min(300, 5 * (2 ** min(record.attempt_count, 6)))
            )
            record.locked_at = None
            record.last_error_code = "billing_transition_failed"
            record.last_error_message = str(exc.detail)[:1000]
            record.save()
            return
        if reconciled.state == MercadoPagoOrder.State.ERROR:
            record.status = MercadoPagoWebhookInbox.Status.RETRYING
            record.next_attempt_at = timezone.now() + timedelta(seconds=min(300, 5 * (2 ** min(record.attempt_count, 6))))
            record.locked_at = None
            record.last_error_code = reconciled.last_error_code
            record.last_error_message = reconciled.last_error_message
            record.save()
            return
        self._finish_inbox(record, MercadoPagoWebhookInbox.Status.PROCESSED)

    @staticmethod
    def _finish_inbox(record, status_value):
        record.status = status_value
        record.next_attempt_at = None
        record.locked_at = None
        record.last_error_code = ""
        record.last_error_message = ""
        record.save()

    @transaction.atomic
    def _claim_order(self):
        now = timezone.now()
        stale = now - timedelta(seconds=settings.MERCADO_PAGO_WORKER_STALE_SECONDS)
        queryset = MercadoPagoOrder.objects.filter(
            state__in=MercadoPagoOrder.ACTIVE_STATES,
        ).filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
        queryset = queryset.filter(Q(locked_at__isnull=True) | Q(locked_at__lte=stale))
        queryset = queryset.select_for_update(skip_locked=True) if connection.features.has_select_for_update_skip_locked else queryset.select_for_update()
        order = queryset.order_by("next_retry_at", "created_at").first()
        if not order:
            return None
        order.locked_at = now
        order.save(update_fields=["locked_at", "updated_at"])
        return order.uuid

    def _process_order(self, order_id):
        try:
            order = MercadoPagoOrder.objects.get(uuid=order_id)
            if not order.external_order_id:
                attempt_create_order(order.uuid, client=self.client)
            elif order.state == MercadoPagoOrder.State.CANCEL_REQUESTED:
                self.client.cancel_order(
                    order.tenant_id, order.external_order_id,
                    idempotency_key=order.cancel_idempotency_key,
                )
                reconcile_order(order.uuid, client=self.client)
            elif order.state == MercadoPagoOrder.State.REFUND_PENDING:
                self.client.refund_order(
                    order.tenant_id, order.external_order_id, amount=order.amount,
                    idempotency_key=order.refund_idempotency_key,
                )
                reconcile_order(order.uuid, client=self.client)
            else:
                reconcile_order(order.uuid, client=self.client)
        except (PlatformBillingError, BillingEnforcementError) as exc:
            order = MercadoPagoOrder.objects.get(uuid=order_id)
            order.retry_count += 1
            order.next_retry_at = timezone.now() + timedelta(
                seconds=min(300, 5 * (2 ** min(order.retry_count, 6)))
            )
            order.last_error_code = "remote_operation_failed"
            order.last_error_message = str(
                exc.message if isinstance(exc, PlatformBillingError) else exc.detail
            )[:1000]
            order.save(
                update_fields=[
                    "retry_count",
                    "next_retry_at",
                    "last_error_code",
                    "last_error_message",
                    "updated_at",
                ]
            )
        finally:
            MercadoPagoOrder.objects.filter(uuid=order_id).update(locked_at=None)
