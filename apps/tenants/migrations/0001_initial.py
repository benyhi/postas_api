import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Tenant",
            fields=[
                ("uuid", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(blank=True, max_length=150)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "tenants",
                "ordering": ["name", "uuid"],
            },
        ),
        migrations.CreateModel(
            name="TenantConfig",
            fields=[
                (
                    "tenant",
                    models.OneToOneField(
                        db_column="tenant_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="config",
                        serialize=False,
                        to="tenants.tenant",
                    ),
                ),
                ("notification_email", models.EmailField(blank=True, max_length=254)),
                ("cashbox_email_notifications_enabled", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "tenant_configs",
            },
        ),
    ]
