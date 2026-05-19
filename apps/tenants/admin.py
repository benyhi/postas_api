from django.contrib import admin

from apps.tenants.models import Tenant, TenantConfig


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("uuid", "name", "active", "created_at")
    list_filter = ("active",)
    search_fields = ("uuid", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TenantConfig)
class TenantConfigAdmin(admin.ModelAdmin):
    list_display = ("tenant", "notification_email", "cashbox_email_notifications_enabled", "updated_at")
    list_filter = ("cashbox_email_notifications_enabled",)
    search_fields = ("tenant__uuid", "tenant__name", "notification_email")
    readonly_fields = ("created_at", "updated_at")
