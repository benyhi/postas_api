from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sales", "0003_sale_split_payment")]
    operations = [
        migrations.AlterField(model_name="sale", name="payment_method", field=models.CharField(choices=[("CASH", "Cash"), ("CARD", "Card"), ("TRANSFER", "Transfer"), ("POINT", "Mercado Pago Point"), ("QR", "Mercado Pago QR"), ("MIXED", "Mixed")], max_length=10)),
        migrations.AlterField(model_name="sale", name="status", field=models.CharField(choices=[("PENDING", "Pending"), ("COMPLETED", "Completed"), ("CANCELLED", "Cancelled")], default="COMPLETED", max_length=10)),
    ]
