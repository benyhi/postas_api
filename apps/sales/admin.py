from django.contrib import admin

from apps.sales.models import Sale, SaleDetail


class SaleDetailInline(admin.TabularInline):
    model = SaleDetail
    extra = 0
    readonly_fields = ("uuid", "product", "quantity", "price", "subtotal")


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("uuid", "total", "payment_method", "status", "user", "created_at", "tenant_id")
    list_filter = ("status", "payment_method", "tenant_id")
    inlines = [SaleDetailInline]
