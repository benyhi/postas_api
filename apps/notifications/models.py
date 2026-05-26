import uuid

from django.db import models


class EmailDelivery(models.Model):
    class Provider(models.TextChoices):
        RESEND = "resend", "Resend"
        DJANGO = "django", "Django email backend"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"

    class NotificationType(models.TextChoices):
        CASHBOX_OPENED = "cashbox_opened", "Cashbox opened"
        CASHBOX_CLOSED = "cashbox_closed", "Cashbox closed"
        PASSWORD_RESET = "password_reset", "Password reset"
        DEBUG = "debug", "Debug"

    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(null=True, blank=True, db_index=True)
    notification_type = models.CharField(max_length=50, choices=NotificationType.choices)
    provider = models.CharField(max_length=30, choices=Provider.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    subject = models.CharField(max_length=255)
    from_email = models.EmailField(max_length=254)
    to_emails = models.JSONField(default=list)
    recipient_count = models.PositiveIntegerField(default=0)
    external_id = models.CharField(max_length=255, blank=True)
    estimated_cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    cost_currency = models.CharField(max_length=3, default="USD")
    provider_response = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    related_entity = models.CharField(max_length=80, blank=True)
    related_entity_id = models.UUIDField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications_email_deliveries"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant_id", "created_at"]),
            models.Index(fields=["provider", "status"]),
            models.Index(fields=["notification_type", "created_at"]),
        ]

    def __str__(self):
        return f"{self.notification_type} {self.provider} {self.status}"
