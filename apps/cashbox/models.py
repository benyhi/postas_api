import uuid

from django.db import models
from django.conf import settings

from core.models.tenant_model import TenantModel


class Cashbox(TenantModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cashboxes_opened",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cashboxes_closed",
    )
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    initial_amount = models.DecimalField(max_digits=12, decimal_places=2)
    final_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    expected_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    difference = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)

    class Meta:
        db_table = "cashboxes"
        ordering = ["-opened_at"]

    def __str__(self):
        return f"Cashbox {self.uuid} ({self.status})"
