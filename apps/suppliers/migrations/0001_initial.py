import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('products', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Supplier',
            fields=[
                ('tenant_id', models.UUIDField(db_index=True)),
                ('active', models.BooleanField(default=True)),
                ('uuid', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=150)),
                ('phone', models.CharField(blank=True, max_length=20)),
                ('email', models.EmailField(blank=True)),
                ('address', models.CharField(blank=True, max_length=200)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'suppliers',
            },
        ),
        migrations.AddConstraint(
            model_name='supplier',
            constraint=models.UniqueConstraint(
                condition=models.Q(active=True),
                fields=['tenant_id', 'name'],
                name='unique_tenant_supplier_name',
            ),
        ),
        migrations.CreateModel(
            name='ProductSupplier',
            fields=[
                ('uuid', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('price', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('is_current', models.BooleanField(default=True)),
                ('since', models.DateField(auto_now_add=True)),
                ('until', models.DateField(blank=True, null=True)),
                ('product', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='product_suppliers',
                    to='products.product',
                )),
                ('supplier', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='product_suppliers',
                    to='suppliers.supplier',
                )),
            ],
            options={
                'db_table': 'product_suppliers',
                'ordering': ['-since'],
            },
        ),
        migrations.AddConstraint(
            model_name='productsupplier',
            constraint=models.UniqueConstraint(
                condition=models.Q(is_current=True),
                fields=['product', 'supplier'],
                name='unique_active_supplier_per_product',
            ),
        ),
    ]
