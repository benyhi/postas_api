import uuid

from django.db import models


class Tenant(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants"
        ordering = ["name", "uuid"]

    def __str__(self):
        return self.name or str(self.uuid)


class TenantConfig(models.Model):
    class ArcaEnvironment(models.TextChoices):
        DEVELOPMENT = "development", "Development"
        PRODUCTION = "production", "Production"

    tenant = models.OneToOneField(
        Tenant,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="config",
        db_column="tenant_id",
    )
    notification_email = models.EmailField(blank=True)
    cashbox_email_notifications_enabled = models.BooleanField(default=True)
    automatic_invoicing_enabled = models.BooleanField(default=False)
    arca_environment = models.CharField(
        max_length=20,
        choices=ArcaEnvironment.choices,
        default=ArcaEnvironment.DEVELOPMENT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenant_configs"

    def __str__(self):
        return f"Config {self.tenant_id}"
