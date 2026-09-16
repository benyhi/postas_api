import uuid

from django.db import models


class MercadoPagoOrder(models.Model):
    class Type(models.TextChoices):
        POINT = "POINT", "Point"
        QR = "QR", "Dynamic QR"

    class State(models.TextChoices):
        CREATING = "CREATING", "Creating"
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        CANCEL_REQUESTED = "CANCEL_REQUESTED", "Cancel requested"
        ACTION_REQUIRED = "ACTION_REQUIRED", "Terminal action required"
        REFUND_PENDING = "REFUND_PENDING", "Refund pending"
        CANCELLED = "CANCELLED", "Cancelled"
        FAILED = "FAILED", "Failed"
        EXPIRED = "EXPIRED", "Expired"
        REFUNDED = "REFUNDED", "Refunded"
        ERROR = "ERROR", "Temporary error"

    ACTIVE_STATES = (
        State.CREATING,
        State.PENDING,
        State.CANCEL_REQUESTED,
        State.ACTION_REQUIRED,
        State.REFUND_PENDING,
        State.ERROR,
    )

    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    sale = models.OneToOneField("sales.Sale", on_delete=models.PROTECT, related_name="mercado_pago_order")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    order_type = models.CharField(max_length=10, choices=Type.choices)
    state = models.CharField(max_length=30, choices=State.choices, default=State.CREATING, db_index=True)
    remote_status = models.CharField(max_length=80, blank=True)
    remote_status_detail = models.CharField(max_length=160, blank=True)
    external_order_id = models.CharField(max_length=160, null=True, blank=True, unique=True)
    external_reference = models.CharField(max_length=160)
    collector_id = models.CharField(max_length=120, blank=True)
    currency = models.CharField(max_length=8, default="ARS")
    live_mode = models.BooleanField(default=False)
    terminal_id = models.CharField(max_length=120, null=True, blank=True)
    pos_id = models.CharField(max_length=120, null=True, blank=True)
    external_pos_id = models.CharField(max_length=120, null=True, blank=True)
    frontend_idempotency_key = models.CharField(max_length=200)
    request_fingerprint = models.CharField(max_length=64)
    create_idempotency_key = models.CharField(max_length=200)
    cancel_idempotency_key = models.CharField(max_length=200, blank=True)
    refund_idempotency_key = models.CharField(max_length=200, blank=True)
    billing_reservation_key = models.CharField(max_length=200)
    billing_reservation_id = models.CharField(max_length=160, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    qr_data = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    reconcile_version = models.PositiveBigIntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    last_error_message = models.TextField(blank=True)
    stock_restored = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mercado_pago_orders"
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "frontend_idempotency_key"], name="mp_order_uq_tenant_front_key"),
        ]
        indexes = [models.Index(fields=["state", "next_retry_at"], name="mp_order_due_idx")]


class MercadoPagoWebhookInbox(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        RETRYING = "RETRYING", "Retrying"
        PROCESSED = "PROCESSED", "Processed"
        IGNORED = "IGNORED", "Ignored"
        FAILED = "FAILED", "Failed"

    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification_key = models.CharField(max_length=64, unique=True)
    request_id = models.CharField(max_length=160)
    data_id = models.CharField(max_length=160, db_index=True)
    topic = models.CharField(max_length=80, blank=True)
    action = models.CharField(max_length=120, blank=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    last_error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mercado_pago_webhook_inbox"
        indexes = [models.Index(fields=["status", "next_attempt_at"], name="mp_webhook_due_idx")]


class MercadoPagoBillingRelease(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    idempotency_key = models.CharField(max_length=160, unique=True)
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(db_index=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "mercado_pago_billing_releases"
        indexes = [
            models.Index(fields=["next_attempt_at", "locked_at"], name="mp_bill_release_due_idx")
        ]
