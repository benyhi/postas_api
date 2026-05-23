import uuid

from django.db import models
from core.models.tenant_model import TenantModel

from django.core.validators import MinValueValidator, MaxValueValidator



class DocumentExtractionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    UPLOADING = "uploading", "Uploading"
    PROCESSING = "processing", "Processing"
    CALLING_AI = "calling_ai", "Calling AI"
    COMPLETED = "completed", "Completed"
    NEEDS_REVIEW = "needs_review", "Needs review"
    FAILED = "failed", "Failed"
    CONFIRMED = "confirmed", "Confirmed"
    CANCELLED = "cancelled", "Cancelled"


class DocumentExtraction(TenantModel):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    file_url = models.URLField(max_length=1000, blank=True, default="")
    file_key = models.CharField(max_length=1000, blank=True, default="")

    status = models.CharField(
        max_length=50,
        choices=DocumentExtractionStatus.choices,
        default=DocumentExtractionStatus.PENDING,
    )

    raw_response = models.JSONField(null=True, blank=True)
    extracted_data = models.JSONField(null=True, blank=True)
    raw_usage = models.JSONField(null=True, blank=True)

    confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )

    ai_extraction_id = models.UUIDField(null=True, blank=True)
    ai_usage_id = models.UUIDField(null=True, blank=True)
    provider = models.CharField(max_length=80, blank=True, default="")
    model = models.CharField(max_length=120, blank=True, default="")
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)

    attempts = models.PositiveSmallIntegerField(default=0)
    error_message = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"DocumentExtraction {self.uuid} - {self.status}"

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "status"]),
            models.Index(fields=["tenant_id", "created_at"]),
        ]
