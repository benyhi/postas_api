from django.contrib import admin

from apps.audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("uuid", "action", "entity", "entity_id", "user", "timestamp", "tenant_id")
    list_filter = ("action", "entity", "tenant_id")
    search_fields = ("entity_id",)
    readonly_fields = (
        "uuid", "tenant_id", "user", "action", "entity",
        "entity_id", "timestamp", "metadata",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
