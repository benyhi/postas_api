from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0004_sale_mercado_pago_choices"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="sale",
            index=models.Index(
                fields=["tenant_id", "status", "-created_at"],
                name="sales_tenant_status_date_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="sale",
            index=models.Index(
                fields=["tenant_id", "-created_at"],
                name="sales_tenant_created_idx",
            ),
        ),
    ]
