import uuid

from django.db import models


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "CREATE", "Create"
        UPDATE = "UPDATE", "Update"
        DELETE = "DELETE", "Delete"
        LOGIN = "LOGIN", "Login"
        SALE = "SALE", "Sale"
        CASHBOX = "CASHBOX", "Cashbox"
        CASHBOX_EMAIL = "CASHBOX_EMAIL", "Cashbox email"
        CASHBOX_EMAIL_SKIP = "CASHBOX_EMAIL_SKIP", "Cashbox email skipped"
        CASHBOX_EMAIL_FAILED = "CASHBOX_EMAIL_FAILED", "Cashbox email failed"

    class Entity(models.TextChoices):
        USER = "USER", "User"
        PRODUCT = "PRODUCT", "Product"
        CATEGORY = "CATEGORY", "Category"
        SALE = "SALE", "Sale"
        CASHBOX = "CASHBOX", "Cashbox"
        CASH_REGISTER = "CASH_REGISTER", "Cash register"
        TENANT_CONFIG = "TENANT_CONFIG", "Tenant config"

    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant_id = models.UUIDField(db_index=True)
    user = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    entity = models.CharField(max_length=20, choices=Entity.choices)
    entity_id = models.UUIDField()
    timestamp = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "audit_logs"
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.action} {self.entity} by {self.user_id} at {self.timestamp}"
