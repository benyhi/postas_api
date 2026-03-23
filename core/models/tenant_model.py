from django.db import models

class TenantModel(models.Model):
    tenant_id = models.UUIDField(db_index=True)
    active = models.BooleanField(default=True)

    class Meta:
        abstract = True