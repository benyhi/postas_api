from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="image_url",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
    ]
