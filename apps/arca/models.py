import uuid

from django.conf import settings
from django.db import models


class FiscalOutboxRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        RETRYING = "retrying", "Retrying"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    sale = models.OneToOneField(
        "sales.Sale",
        on_delete=models.PROTECT,
        related_name="fiscal_request",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="fiscal_requests",
    )
    environment = models.CharField(max_length=20)
    external_id = models.CharField(max_length=160)
    payload_snapshot = models.JSONField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    invoice_status = models.CharField(max_length=40, default="pending")
    platform_invoice_id = models.BigIntegerField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=80, blank=True)
    last_error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "arca_fiscal_outbox"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "external_id"],
                name="uq_arca_outbox_tenant_external",
            )
        ]
        indexes = [
            models.Index(fields=["status", "next_attempt_at"], name="ix_arca_outbox_due"),
        ]
