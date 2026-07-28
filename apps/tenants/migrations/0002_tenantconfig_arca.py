from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tenants", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="tenantconfig",
            name="automatic_invoicing_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="tenantconfig",
            name="arca_environment",
            field=models.CharField(
                choices=[("development", "Development"), ("production", "Production")],
                default="development",
                max_length=20,
            ),
        ),
    ]
