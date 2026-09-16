from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("cashbox", "0003_cashregister_cashbox_register_and_more")]
    operations = [
        migrations.AddField(model_name="cashregister", name="mercado_pago_terminal_id", field=models.CharField(blank=True, max_length=120, null=True)),
        migrations.AddField(model_name="cashregister", name="mercado_pago_pos_id", field=models.CharField(blank=True, max_length=120, null=True)),
        migrations.AddField(model_name="cashregister", name="mercado_pago_external_pos_id", field=models.CharField(blank=True, max_length=120, null=True)),
        migrations.AddConstraint(model_name="cashregister", constraint=models.UniqueConstraint(fields=("tenant_id", "mercado_pago_terminal_id"), condition=models.Q(mercado_pago_terminal_id__isnull=False), name="cashreg_uq_tenant_mp_terminal")),
        migrations.AddConstraint(model_name="cashregister", constraint=models.UniqueConstraint(fields=("tenant_id", "mercado_pago_pos_id"), condition=models.Q(mercado_pago_pos_id__isnull=False), name="cashreg_uq_tenant_mp_pos")),
        migrations.AddConstraint(model_name="cashregister", constraint=models.UniqueConstraint(fields=("tenant_id", "mercado_pago_external_pos_id"), condition=models.Q(mercado_pago_external_pos_id__isnull=False), name="cashreg_uq_tenant_mp_ext_pos")),
    ]
