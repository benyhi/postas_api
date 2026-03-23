import uuid

from django.db import models

from core.models.tenant_model import TenantModel


class ActiveManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(active=True)


class Category(TenantModel):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        db_table = "categories"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "name"],
                condition=models.Q(active=True),
                name="unique_tenant_category_name",
            ),
        ]

    def __str__(self):
        return self.name


class Product(TenantModel):
    class Unit(models.TextChoices):
        KG = "KG", "Kilogram"
        U = "U", "Unit"

    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    price = models.DecimalField(max_digits=12, decimal_places=2)
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unit = models.CharField(max_length=5, choices=Unit.choices, default=Unit.U)
    stock = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    min_stock = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    barcode = models.CharField(max_length=100, blank=True, default="")
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        db_table = "products"
        indexes = [
            models.Index(fields=["barcode"], name="idx_product_barcode"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "name"],
                condition=models.Q(active=True),
                name="unique_tenant_product_name",
            ),
            models.UniqueConstraint(
                fields=["tenant_id", "barcode"],
                condition=models.Q(active=True) & ~models.Q(barcode=""),
                name="unique_tenant_product_barcode",
            ),
        ]

    def __str__(self):
        return self.name
