from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.users.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("uuid", "username", "email", "role", "tenant_id", "active")
    list_filter = ("role", "active", "tenant_id")
    search_fields = ("username", "email")
    ordering = ("-created_at",)

    fieldsets = (
        (None, {"fields": ("username", "email", "password")}),
        ("Tenant", {"fields": ("tenant_id",)}),
        ("Role & Status", {"fields": ("role", "active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("tenant_id", "username", "email", "password1", "password2", "role"),
        }),
    )
