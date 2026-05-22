from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sales', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='sale',
            name='payments',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name='sale',
            name='payment_method',
            field=models.CharField(
                choices=[('CASH', 'Cash'), ('CARD', 'Card'), ('TRANSFER', 'Transfer'), ('MIXED', 'Mixed')],
                max_length=10,
            ),
        ),
    ]
