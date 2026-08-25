from django.contrib import admin

from apps.cashbox.models import Cashbox, CashRegister


@admin.register(CashRegister)
class CashRegisterAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant_id", "active", "created_at", "updated_at")
    list_filter = ("active",)
    search_fields = ("name", "tenant_id")


@admin.register(Cashbox)
class CashboxAdmin(admin.ModelAdmin):
    list_display = ("uuid", "status", "register", "opened_by", "opened_at", "closed_at", "tenant_id")
    list_filter = ("status", "tenant_id")
