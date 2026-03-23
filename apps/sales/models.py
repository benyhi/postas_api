import uuid

from django.db import models
from django.conf import settings

from core.models.tenant_model import TenantModel


class Sale(TenantModel):
    class PaymentMethod(models.TextChoices):
        CASH = "CASH", "Cash"
        CARD = "CARD", "Card"
        TRANSFER = "TRANSFER", "Transfer"

    class Status(models.TextChoices):
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sales",
    )
    cashbox = models.ForeignKey(
        "cashbox.Cashbox",
        on_delete=models.PROTECT,
        related_name="sales",
    )
    total = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.COMPLETED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sales"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Sale {self.uuid} - {self.total}"


class SaleDetail(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="details")
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.PROTECT,
        related_name="sale_details",
    )
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    price = models.DecimalField(max_digits=12, decimal_places=2)  # snapshot
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = "sale_details"

    def __str__(self):
        return f"{self.product} x {self.quantity}"
