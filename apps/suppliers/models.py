import uuid

from django.db import models

from core.models.tenant_model import TenantModel


class ActiveManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(active=True)


class Supplier(TenantModel):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        db_table = "suppliers"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "name"],
                condition=models.Q(active=True),
                name="unique_tenant_supplier_name",
            ),
        ]

    def __str__(self):
        return self.name


class ProductSupplier(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.CASCADE,
        related_name="product_suppliers",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.CASCADE,
        related_name="product_suppliers",
    )
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_current = models.BooleanField(default=True)
    since = models.DateField(auto_now_add=True)
    until = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "product_suppliers"
        ordering = ["-since"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "supplier"],
                condition=models.Q(is_current=True),
                name="unique_active_supplier_per_product",
            ),
        ]

    def __str__(self):
        return f"{self.supplier} → {self.product}"
