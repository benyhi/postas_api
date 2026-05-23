from django.contrib import admin

from .models import DocumentExtraction


@admin.register(DocumentExtraction)
class DocumentExtractionAdmin(admin.ModelAdmin):
    list_display = ("uuid", "tenant_id", "status", "confidence", "provider", "model", "created_at")
    list_filter = ("status", "provider", "model", "created_at")
    search_fields = ("uuid", "tenant_id", "file_key", "error_message")
    readonly_fields = ("uuid", "created_at", "updated_at")
