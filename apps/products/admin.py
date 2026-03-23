from django.contrib import admin

from apps.products.models import Category, Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("uuid", "name", "tenant_id", "active", "created_at")
    list_filter = ("active", "tenant_id")
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("uuid", "name", "price", "stock", "unit", "tenant_id", "active")
    list_filter = ("active", "unit", "tenant_id", "category")
    search_fields = ("name", "barcode")
