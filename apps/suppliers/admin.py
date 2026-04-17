from django.contrib import admin

from apps.suppliers.models import Supplier, ProductSupplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("uuid", "name", "phone", "email", "tenant_id", "active", "created_at")
    list_filter = ("active", "tenant_id")
    search_fields = ("name", "email", "phone")


@admin.register(ProductSupplier)
class ProductSupplierAdmin(admin.ModelAdmin):
    list_display = ("uuid", "product", "supplier", "price", "is_current", "since", "until")
    list_filter = ("is_current",)
    search_fields = ("product__name", "supplier__name")
