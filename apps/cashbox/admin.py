from django.contrib import admin

from apps.cashbox.models import Cashbox


@admin.register(Cashbox)
class CashboxAdmin(admin.ModelAdmin):
    list_display = ("uuid", "status", "opened_by", "opened_at", "closed_at", "tenant_id")
    list_filter = ("status", "tenant_id")

    
