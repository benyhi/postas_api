import json
import os
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib import error, request

from django.conf import settings
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from apps.platform_billing.client import PlatformBillingClient, PlatformBillingError
from core.cloud.service import get_image_service

from .models import DocumentExtraction, DocumentExtractionStatus


DOCUMENT_EXTRACTION_FEATURE_KEY = "document_extraction"
DOCUMENT_EXTRACTION_USAGE_PREFIX = "document-extraction"


class DocumentExtractionError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        extraction: DocumentExtraction | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.extraction = extraction


class AIExtractorClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        source: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.AI_EXTRACTOR_BASE_URL).rstrip("/")
        self.token = token if token is not None else settings.AI_EXTRACTOR_TOKEN
        self.source = source if source is not None else settings.AI_EXTRACTOR_SOURCE
        self.timeout = timeout or settings.AI_EXTRACTOR_TIMEOUT

    def extract(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.source:
            headers["X-Postas-Source"] = self.source

        req = request.Request(
            f"{self.base_url}/document-extractions/process",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            raise DocumentExtractionError(self._error_message(exc), status_code=502) from exc
        except error.URLError as exc:
            raise DocumentExtractionError(f"No se pudo conectar con la API IA: {exc.reason}", status_code=502) from exc
        except TimeoutError as exc:
            raise DocumentExtractionError("Timeout esperando respuesta de la API IA.", status_code=504) from exc

        try:
            parsed = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError as exc:
            raise DocumentExtractionError("La API IA devolvio una respuesta JSON invalida.", status_code=502) from exc
        if not isinstance(parsed, dict):
            raise DocumentExtractionError("La API IA devolvio un formato inesperado.", status_code=502)
        return parsed

    @staticmethod
    def _error_message(exc: error.HTTPError) -> str:
        raw_body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            detail = parsed.get("detail") or parsed.get("error") or parsed.get("message")
            if detail:
                return str(detail)
        return raw_body or f"La API IA respondio con HTTP {exc.code}."


class DocumentExtractionService:
    def __init__(
        self,
        client: AIExtractorClient | None = None,
        platform_client: PlatformBillingClient | None = None,
    ) -> None:
        self.client = client or AIExtractorClient()
        self.platform_client = platform_client or PlatformBillingClient()

    def extract_from_upload(
        self,
        *,
        request_obj,
        image_file,
        provider: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DocumentExtraction:
        self._validate_image(image_file)
        self._check_document_extraction_entitlement(request_obj.tenant_id)

        extraction = DocumentExtraction.objects.create(
            tenant_id=request_obj.tenant_id,
            status=DocumentExtractionStatus.PENDING,
        )

        try:
            self._set_status(extraction, DocumentExtractionStatus.UPLOADING)
            upload_result = self._upload_image(request_obj.tenant_id, image_file)
            extraction.file_url = upload_result["url"]
            extraction.file_key = upload_result["key"]
            extraction.save(update_fields=["file_url", "file_key", "updated_at"])

            signed_url = self._signed_image_url(upload_result["key"])
            self._set_status(
                extraction,
                DocumentExtractionStatus.CALLING_AI,
                processing_started_at=timezone.now(),
                attempts=extraction.attempts + 1,
            )

            payload = self._build_ai_payload(
                extraction=extraction,
                signed_image_url=signed_url,
                provider=provider,
                metadata=metadata or {},
            )
            ai_response = self.client.extract(payload)
            self._apply_ai_response(extraction, ai_response)
            if self._should_consume_platform_usage(extraction):
                self._consume_document_extraction_usage(extraction)
            return extraction
        except DocumentExtractionError as exc:
            self._mark_failed(extraction, exc.message)
            exc.extraction = extraction
            raise
        except Exception as exc:
            self._mark_failed(extraction, str(exc))
            raise DocumentExtractionError(str(exc), status_code=500, extraction=extraction) from exc

    def _check_document_extraction_entitlement(self, tenant_id) -> None:
        resource_count = self._current_monthly_usage(tenant_id)
        try:
            response = self.platform_client.check_entitlement(
                tenant_id,
                DOCUMENT_EXTRACTION_FEATURE_KEY,
                amount=1,
                resource_count=resource_count,
                context={
                    "source": "document_extractor",
                    "operation": "extract_from_upload",
                },
            )
        except PlatformBillingError as exc:
            raise DocumentExtractionError(
                "No se pudo validar el permiso del plan. Intenta nuevamente.",
                status_code=_platform_error_status(exc),
            ) from exc

        allowed = response.get("allowed")
        if allowed is True:
            return
        if allowed is False:
            raise DocumentExtractionError(
                _entitlement_denied_message(response),
                status_code=403,
            )
        raise DocumentExtractionError(
            "La plataforma de planes no confirmo el permiso para usar extraccion de documentos.",
            status_code=503,
        )

    def _current_monthly_usage(self, tenant_id) -> int:
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return DocumentExtraction.objects.filter(
            tenant_id=tenant_id,
            created_at__gte=month_start,
            status__in=[
                DocumentExtractionStatus.COMPLETED,
                DocumentExtractionStatus.NEEDS_REVIEW,
                DocumentExtractionStatus.CONFIRMED,
            ],
        ).count()

    def _validate_image(self, image_file) -> None:
        allowed = getattr(settings, "DOCUMENT_EXTRACTOR_ALLOWED_EXTENSIONS", (".jpg", ".jpeg", ".png"))
        ext = os.path.splitext(getattr(image_file, "name", ""))[1].lower()
        if ext not in allowed:
            raise DocumentExtractionError(f"Formato no permitido. Permitidos: {', '.join(allowed)}")

        max_size = int(getattr(settings, "DOCUMENT_EXTRACTOR_MAX_IMAGE_SIZE", 0) or 0)
        size = getattr(image_file, "size", 0) or 0
        if max_size > 0 and size > max_size:
            raise DocumentExtractionError("La imagen supera el tamano maximo permitido.")

    def _upload_image(self, tenant_id, image_file) -> dict[str, str]:
        try:
            service = get_image_service()
        except ValueError as exc:
            raise DocumentExtractionError(f"Almacenamiento no configurado: {exc}", status_code=503) from exc

        folder = f"{tenant_id}/document-extractions"
        result = service.upload(image_file, image_file.name, folder=folder)
        if not result.get("success"):
            raise DocumentExtractionError(result.get("error") or "No se pudo subir la imagen.", status_code=502)
        return {"key": result["key"], "url": result["url"]}

    def _signed_image_url(self, key: str) -> str:
        service = get_image_service()
        result = service.presigned_get_url(
            key,
            expires_in=int(getattr(settings, "DOCUMENT_EXTRACTOR_PRESIGNED_URL_TTL", 600)),
        )
        if not result.get("success"):
            raise DocumentExtractionError(result.get("error") or "No se pudo firmar la URL de la imagen.", status_code=502)
        return result["url"]

    def _build_ai_payload(
        self,
        *,
        extraction: DocumentExtraction,
        signed_image_url: str,
        provider: str | None,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "uuid": str(extraction.uuid),
            "tenant_id": str(extraction.tenant_id),
            "file_url": signed_image_url,
            "status": extraction.status,
            "raw_response": extraction.raw_response,
            "extracted_data": extraction.extracted_data,
            "confidence": float(extraction.confidence) if extraction.confidence is not None else None,
            "attempts": extraction.attempts,
            "error_message": extraction.error_message,
            "created_at": extraction.created_at.isoformat() if extraction.created_at else None,
            "updated_at": extraction.updated_at.isoformat() if extraction.updated_at else None,
            "processing_started_at": (
                extraction.processing_started_at.isoformat()
                if extraction.processing_started_at
                else None
            ),
            "completed_at": extraction.completed_at.isoformat() if extraction.completed_at else None,
            "confirmed_at": extraction.confirmed_at.isoformat() if extraction.confirmed_at else None,
            "metadata": {
                "source": "postas_api",
                "stored_file_url": extraction.file_url,
                "file_key": extraction.file_key,
                **metadata,
            },
        }
        if provider:
            payload["provider"] = provider
        return payload

    def _apply_ai_response(self, extraction: DocumentExtraction, response: dict[str, Any]) -> None:
        products = _extract_products(response)
        confidence = _extract_confidence(response)
        status_value = _map_status(response.get("status"), confidence)
        usage = _extract_usage(response)

        extraction.raw_response = response
        extraction.raw_usage = usage
        extraction.extracted_data = {
            "products": products,
            "date": _nested_get(response, "date"),
            "total": _nested_get(response, "total"),
            "is_invoice": _nested_get(response, "is_invoice"),
        }
        extraction.confidence = _to_decimal(confidence, places=4) if confidence is not None else None
        extraction.status = status_value
        extraction.error_message = response.get("error_message") or response.get("error")
        extraction.ai_extraction_id = _to_uuid(response.get("extraction_id") or response.get("uuid"))
        extraction.ai_usage_id = _to_uuid(response.get("usage_id"))
        extraction.provider = str(response.get("provider") or usage.get("provider") or "")
        extraction.model = str(response.get("model") or usage.get("model") or "")
        extraction.prompt_tokens = _to_int(usage.get("prompt_tokens"))
        extraction.completion_tokens = _to_int(usage.get("completion_tokens"))
        extraction.total_tokens = _to_int(usage.get("total_tokens"))
        extraction.estimated_cost_usd = _to_decimal(usage.get("estimated_cost_usd"), places=6) or Decimal("0")
        extraction.latency_ms = _to_int(usage.get("latency_ms")) if usage.get("latency_ms") is not None else None
        extraction.attempts = _to_int(response.get("attempts")) or extraction.attempts
        extraction.processing_started_at = _to_datetime(response.get("processing_started_at")) or extraction.processing_started_at
        extraction.completed_at = _to_datetime(response.get("completed_at")) or timezone.now()
        extraction.save()

    def _consume_document_extraction_usage(self, extraction: DocumentExtraction) -> None:
        try:
            response = self.platform_client.check_and_consume(
                extraction.tenant_id,
                DOCUMENT_EXTRACTION_FEATURE_KEY,
                amount=1,
                external_id=extraction.uuid,
                idempotency_key=f"{DOCUMENT_EXTRACTION_USAGE_PREFIX}:{extraction.uuid}",
                occurred_at=extraction.completed_at,
                metadata=_document_extraction_usage_metadata(extraction),
                context={
                    "source": "document_extractor",
                    "operation": "consume_after_successful_extraction",
                },
            )
        except PlatformBillingError as exc:
            if _is_duplicate_usage_response(exc):
                return
            raise DocumentExtractionError(
                "No se pudo registrar el consumo del plan. Intenta nuevamente.",
                status_code=_platform_error_status(exc),
                extraction=extraction,
            ) from exc
        if _is_confirmed_usage_response(response):
            return
        raise DocumentExtractionError(
            _usage_consume_failure_message(response),
            status_code=_usage_consume_failure_status(response),
            extraction=extraction,
        )

    @staticmethod
    def _should_consume_platform_usage(extraction: DocumentExtraction) -> bool:
        return extraction.status in {
            DocumentExtractionStatus.COMPLETED,
            DocumentExtractionStatus.NEEDS_REVIEW,
        }

    def _set_status(self, extraction: DocumentExtraction, status: str, **extra_fields: Any) -> None:
        extraction.status = status
        update_fields = ["status", "updated_at"]
        for field, value in extra_fields.items():
            setattr(extraction, field, value)
            update_fields.append(field)
        extraction.save(update_fields=update_fields)

    def _mark_failed(self, extraction: DocumentExtraction, error_message: str) -> None:
        extraction.status = DocumentExtractionStatus.FAILED
        extraction.error_message = error_message
        extraction.completed_at = timezone.now()
        extraction.save(update_fields=["status", "error_message", "completed_at", "updated_at"])


def _nested_get(data: dict[str, Any], key: str) -> Any:
    if key in data:
        return data.get(key)
    for nested_key in ("data", "extracted_data", "invoice"):
        nested = data.get(nested_key)
        if isinstance(nested, dict) and key in nested:
            return nested.get(key)
    return None


def _entitlement_denied_message(response: dict[str, Any]) -> str:
    detail = (
        response.get("message")
        or response.get("detail")
        or response.get("reason")
        or response.get("error")
    )
    if detail:
        return str(detail)
    return "Tu plan no permite usar extraccion de documentos."


def _platform_error_status(exc: PlatformBillingError) -> int:
    if 400 <= exc.status_code <= 599:
        return exc.status_code
    return 503


def _document_extraction_usage_metadata(extraction: DocumentExtraction) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "provider": extraction.provider,
        "model": extraction.model,
        "status": extraction.status,
        "estimated_cost_usd": str(extraction.estimated_cost_usd),
        "prompt_tokens": extraction.prompt_tokens,
        "completion_tokens": extraction.completion_tokens,
        "total_tokens": extraction.total_tokens,
        "latency_ms": extraction.latency_ms,
    }
    if extraction.ai_extraction_id:
        metadata["ai_extraction_id"] = str(extraction.ai_extraction_id)
    if extraction.ai_usage_id:
        metadata["ai_usage_id"] = str(extraction.ai_usage_id)
    return metadata


def _is_confirmed_usage_response(response: dict[str, Any]) -> bool:
    if _is_duplicate_usage_data(response):
        return True
    if _has_explicit_usage_denial(response):
        return False
    if response.get("consumed") is True:
        return True
    if response.get("recorded") is True:
        return True
    if response.get("created") is True:
        return True
    if response.get("usage_id") or response.get("id"):
        return True
    usage = response.get("usage")
    return isinstance(usage, dict) and bool(usage.get("id") or usage.get("uuid"))


def _has_explicit_usage_denial(response: dict[str, Any]) -> bool:
    for key in ("allowed", "consumed", "recorded", "created"):
        if response.get(key) is False:
            return True
    usage = response.get("usage")
    if isinstance(usage, dict):
        for key in ("allowed", "consumed", "recorded", "created"):
            if usage.get(key) is False:
                return True
    return False


def _is_duplicate_usage_data(data: dict[str, Any]) -> bool:
    code = str(data.get("code") or data.get("error_code") or "").lower()
    detail = str(data.get("detail") or data.get("message") or data.get("error") or "").lower()
    status = str(data.get("status") or "").lower()
    duplicate_codes = {
        "duplicate_usage",
        "usage_already_consumed",
        "usage_already_recorded",
        "idempotency_key_exists",
        "idempotency_duplicate",
        "idempotent_replay",
    }
    return (
        data.get("duplicate") is True
        or data.get("idempotent") is True
        or data.get("already_recorded") is True
        or code in duplicate_codes
        or status in {"duplicate", "already_consumed", "idempotent_replay"}
        or ("idempotency" in detail and "duplicate" in detail)
        or ("already" in detail and "consum" in detail)
        or ("already" in detail and "record" in detail)
    )


def _usage_consume_failure_message(response: dict[str, Any]) -> str:
    detail = (
        response.get("message")
        or response.get("detail")
        or response.get("reason")
        or response.get("error")
    )
    if detail:
        return str(detail)
    return "La plataforma de planes no confirmo el registro del consumo."


def _usage_consume_failure_status(response: dict[str, Any]) -> int:
    text = " ".join(
        str(response.get(key) or "").lower()
        for key in ("code", "error_code", "message", "detail", "reason", "error")
    )
    if "limit" in text or "quota" in text or "over" in text:
        return 429
    if response.get("allowed") is False:
        return 403
    return 503


def _is_duplicate_usage_response(exc: PlatformBillingError) -> bool:
    if exc.status_code != 409:
        return False
    return _is_duplicate_usage_data(exc.response_data)


def _extract_products(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_products = _nested_get(data, "products")
    if raw_products is None:
        raw_products = _nested_get(data, "items")
    if not isinstance(raw_products, list):
        return []

    products: list[dict[str, Any]] = []
    for item in raw_products:
        if not isinstance(item, dict):
            continue
        product = {
            "code": item.get("code") or item.get("barcode") or item.get("sku"),
            "description": item.get("description") or item.get("name") or item.get("product"),
            "quantity": _to_float(item.get("quantity") or item.get("qty")),
            "price": _to_float(item.get("price") or item.get("unit_price") or item.get("unitPrice")),
            "total": _to_float(item.get("total") or item.get("line_total") or item.get("lineTotal")),
        }
        products.append({key: value for key, value in product.items() if value is not None})
    return products


def _extract_confidence(data: dict[str, Any]) -> float | None:
    value = (
        data.get("confidence_score")
        if data.get("confidence_score") is not None
        else data.get("confidence")
    )
    if value is None:
        value = _nested_get(data, "confidence_score")
    if value is None:
        value = _nested_get(data, "confidence")
    parsed = _to_float(value)
    if parsed is None:
        return None
    if parsed > 1:
        parsed = parsed / 100
    return max(0.0, min(1.0, parsed))


def _extract_usage(data: dict[str, Any]) -> dict[str, Any]:
    usage = data.get("usage") or data.get("usage_summary") or data.get("token_usage") or {}
    if not isinstance(usage, dict):
        usage = {}

    for field in ("prompt_tokens", "completion_tokens", "total_tokens", "estimated_cost_usd", "latency_ms"):
        if field not in usage and data.get(field) is not None:
            usage[field] = data.get(field)
    return usage


def _map_status(ai_status: Any, confidence: float | None) -> str:
    normalized = str(ai_status or "").lower()
    if normalized in {"processed", "completed", "complete", "success", "succeeded"}:
        return DocumentExtractionStatus.COMPLETED
    if normalized in {"needs_review", "review", "low_confidence"}:
        return DocumentExtractionStatus.NEEDS_REVIEW
    if normalized in {"failed", "error", "not_invoice"}:
        return DocumentExtractionStatus.FAILED

    if confidence is None:
        return DocumentExtractionStatus.NEEDS_REVIEW
    if confidence >= settings.DOCUMENT_EXTRACTOR_ACCEPTED_CONFIDENCE:
        return DocumentExtractionStatus.COMPLETED
    if confidence >= settings.DOCUMENT_EXTRACTOR_MIN_CONFIDENCE:
        return DocumentExtractionStatus.NEEDS_REVIEW
    return DocumentExtractionStatus.FAILED


def _to_int(value: Any) -> int:
    parsed = _to_float(value)
    return int(parsed or 0)


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _to_decimal(value: Any, places: int) -> Decimal | None:
    parsed = _to_float(value)
    if parsed is None:
        return None
    try:
        quant = Decimal("1").scaleb(-places)
        return Decimal(str(parsed)).quantize(quant)
    except (InvalidOperation, ValueError):
        return None


def _to_uuid(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _to_datetime(value: Any):
    if not value:
        return None
    if hasattr(value, "isoformat"):
        return value
    parsed = parse_datetime(str(value))
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone=timezone.get_current_timezone())
    return parsed
