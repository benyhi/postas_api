import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("sales", "0003_sale_split_payment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FiscalOutboxRequest",
            fields=[
                ("uuid", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tenant_id", models.UUIDField(db_index=True)),
                ("environment", models.CharField(max_length=20)),
                ("external_id", models.CharField(max_length=160)),
                ("payload_snapshot", models.JSONField()),
                ("status", models.CharField(choices=[("pending", "Pending"), ("sending", "Sending"), ("retrying", "Retrying"), ("sent", "Sent"), ("failed", "Failed")], db_index=True, default="pending", max_length=20)),
                ("invoice_status", models.CharField(default="pending", max_length=40)),
                ("platform_invoice_id", models.BigIntegerField(blank=True, null=True)),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("next_attempt_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("locked_at", models.DateTimeField(blank=True, null=True)),
                ("last_error_code", models.CharField(blank=True, max_length=80)),
                ("last_error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="fiscal_requests", to=settings.AUTH_USER_MODEL)),
                ("sale", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="fiscal_request", to="sales.sale")),
            ],
            options={"db_table": "arca_fiscal_outbox"},
        ),
        migrations.AddConstraint(
            model_name="fiscaloutboxrequest",
            constraint=models.UniqueConstraint(fields=("tenant_id", "external_id"), name="uq_arca_outbox_tenant_external"),
        ),
        migrations.AddIndex(
            model_name="fiscaloutboxrequest",
            index=models.Index(fields=["status", "next_attempt_at"], name="ix_arca_outbox_due"),
        ),
    ]
