import uuid

from django.db import models
from django.conf import settings

from core.models.tenant_model import TenantModel


class CashRegister(TenantModel):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    mercado_pago_terminal_id = models.CharField(max_length=120, null=True, blank=True)
    mercado_pago_pos_id = models.CharField(max_length=120, null=True, blank=True)
    mercado_pago_external_pos_id = models.CharField(max_length=120, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cash_registers"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "name"],
                name="cash_register_unique_tenant_name",
            ),
            models.UniqueConstraint(
                fields=["tenant_id", "mercado_pago_terminal_id"],
                condition=models.Q(mercado_pago_terminal_id__isnull=False),
                name="cashreg_uq_tenant_mp_terminal",
            ),
            models.UniqueConstraint(
                fields=["tenant_id", "mercado_pago_pos_id"],
                condition=models.Q(mercado_pago_pos_id__isnull=False),
                name="cashreg_uq_tenant_mp_pos",
            ),
            models.UniqueConstraint(
                fields=["tenant_id", "mercado_pago_external_pos_id"],
                condition=models.Q(mercado_pago_external_pos_id__isnull=False),
                name="cashreg_uq_tenant_mp_ext_pos",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.tenant_id})"


class Cashbox(TenantModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    register = models.ForeignKey(
        CashRegister,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cashboxes",
    )
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
        constraints = [
            models.UniqueConstraint(
                fields=["register"],
                condition=models.Q(status="OPEN"),
                name="cashbox_unique_open_register",
            ),
            models.UniqueConstraint(
                fields=["opened_by"],
                condition=models.Q(status="OPEN"),
                name="cashbox_unique_open_user",
            ),
        ]

    def __str__(self):
        return f"Cashbox {self.uuid} ({self.status})"
