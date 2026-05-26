from django.contrib import admin

from apps.notifications.models import EmailDelivery


@admin.register(EmailDelivery)
class EmailDeliveryAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "tenant_id",
        "notification_type",
        "provider",
        "status",
        "recipient_count",
        "estimated_cost_usd",
    )
    list_filter = ("provider", "status", "notification_type", "created_at")
    search_fields = ("subject", "external_id", "error_message")
    readonly_fields = (
        "uuid",
        "created_at",
        "updated_at",
        "sent_at",
        "provider_response",
        "metadata",
    )
