import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.platform_billing.client import PlatformBillingError

from .models import DocumentExtraction, DocumentExtractionStatus
from .services import AIExtractorClient, DocumentExtractionError, DocumentExtractionService


class FakeImageService:
    def upload(self, file_obj, filename, folder="images"):
        return {
            "success": True,
            "key": f"{folder}/invoice.jpg",
            "url": "https://cdn.example.com/invoice.jpg",
        }

    def presigned_get_url(self, key, expires_in=600):
        return {
            "success": True,
            "key": key,
            "url": f"https://signed.example.com/{key}?ttl={expires_in}",
        }


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.payload = None
        self.calls = 0

    def extract(self, payload):
        self.calls += 1
        self.payload = payload
        return self.response


class FakePlatformClient:
    def __init__(
        self,
        *,
        entitlement_response=None,
        entitlement_error=None,
        consume_response=None,
        consume_error=None,
    ):
        self.entitlement_response = entitlement_response or {"allowed": True}
        self.entitlement_error = entitlement_error
        self.consume_response = consume_response or {"allowed": True, "recorded": True}
        self.consume_error = consume_error
        self.entitlement_calls = []
        self.consume_calls = []

    def check_entitlement(self, tenant_id, feature_key, **kwargs):
        self.entitlement_calls.append(
            {
                "tenant_id": tenant_id,
                "feature_key": feature_key,
                **kwargs,
            }
        )
        if self.entitlement_error:
            raise self.entitlement_error
        return self.entitlement_response

    def consume_usage(self, tenant_id, feature_key, **kwargs):
        self.consume_calls.append(
            {
                "tenant_id": tenant_id,
                "feature_key": feature_key,
                **kwargs,
            }
        )
        if self.consume_error:
            raise self.consume_error
        return self.consume_response

    def check_and_consume(self, tenant_id, feature_key, **kwargs):
        return self.consume_usage(tenant_id, feature_key, **kwargs)


@override_settings(
    DOCUMENT_EXTRACTOR_ALLOWED_EXTENSIONS=(".jpg", ".jpeg", ".png"),
    DOCUMENT_EXTRACTOR_MAX_IMAGE_SIZE=1024 * 1024,
    DOCUMENT_EXTRACTOR_PRESIGNED_URL_TTL=300,
)
class DocumentExtractionServiceTests(TestCase):
    def test_check_entitlement_allowed_true_persists_ai_response_and_consumes_usage(self):
        tenant_id = uuid.uuid4()
        request_obj = SimpleNamespace(tenant_id=tenant_id)
        image = SimpleUploadedFile("invoice.jpg", b"image-bytes", content_type="image/jpeg")
        platform_client = FakePlatformClient()
        client = FakeClient(
            {
                "uuid": str(uuid.uuid4()),
                "status": "completed",
                "confidence": 0.92,
                "extracted_data": {
                    "products": [
                        {"code": "779", "description": "Yerba", "quantity": 2, "price": 1500, "total": 3000}
                    ],
                    "date": "2026-05-23",
                    "total": 3000,
                    "is_invoice": True,
                },
                "attempts": 1,
                "usage": {
                    "provider": "mock",
                    "model": "mock-v1",
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                    "estimated_cost_usd": 0.001,
                    "latency_ms": 1200,
                },
            }
        )

        with patch("apps.document_extractor.services.get_image_service", return_value=FakeImageService()):
            extraction = DocumentExtractionService(
                client=client,
                platform_client=platform_client,
            ).extract_from_upload(
                request_obj=request_obj,
                image_file=image,
                provider="mock",
                metadata={"source_screen": "purchase_upload"},
            )

        extraction.refresh_from_db()
        self.assertEqual(extraction.status, DocumentExtractionStatus.COMPLETED)
        self.assertEqual(float(extraction.confidence), 0.92)
        self.assertEqual(extraction.total_tokens, 150)
        self.assertEqual(extraction.provider, "mock")
        self.assertEqual(extraction.extracted_data["products"][0]["description"], "Yerba")
        self.assertEqual(client.payload["tenant_id"], str(tenant_id))
        self.assertEqual(client.payload["provider"], "mock")
        self.assertEqual(client.payload["uuid"], str(extraction.uuid))
        self.assertEqual(client.payload["file_url"], "https://signed.example.com/{}/document-extractions/invoice.jpg?ttl=300".format(tenant_id))
        self.assertEqual(client.payload["attempts"], 1)
        self.assertEqual(client.payload["status"], DocumentExtractionStatus.CALLING_AI)
        self.assertEqual(len(platform_client.entitlement_calls), 1)
        entitlement_call = platform_client.entitlement_calls[0]
        self.assertEqual(entitlement_call["tenant_id"], tenant_id)
        self.assertEqual(entitlement_call["feature_key"], "document_extraction")
        self.assertEqual(entitlement_call["amount"], 1)
        self.assertEqual(entitlement_call["resource_count"], 0)
        self.assertEqual(len(platform_client.consume_calls), 1)
        consume_call = platform_client.consume_calls[0]
        self.assertEqual(consume_call["tenant_id"], tenant_id)
        self.assertEqual(consume_call["feature_key"], "document_extraction")
        self.assertEqual(consume_call["amount"], 1)
        self.assertEqual(consume_call["external_id"], extraction.uuid)
        self.assertEqual(consume_call["idempotency_key"], f"document-extraction:{extraction.uuid}")
        self.assertEqual(consume_call["metadata"]["provider"], "mock")
        self.assertEqual(consume_call["metadata"]["model"], "mock-v1")
        self.assertEqual(consume_call["metadata"]["status"], DocumentExtractionStatus.COMPLETED)
        self.assertEqual(consume_call["metadata"]["total_tokens"], 150)
        self.assertEqual(consume_call["context"]["source"], "document_extractor")
        self.assertEqual(consume_call["context"]["operation"], "consume_after_successful_extraction")

    def test_check_entitlement_allowed_false_blocks_before_upload_and_ai(self):
        tenant_id = uuid.uuid4()
        request_obj = SimpleNamespace(tenant_id=tenant_id)
        image = SimpleUploadedFile("invoice.jpg", b"image-bytes", content_type="image/jpeg")
        client = FakeClient({"status": "completed", "products": []})
        platform_client = FakePlatformClient(
            entitlement_response={
                "allowed": False,
                "reason": "feature_not_enabled",
                "message": "Tu plan no incluye extraccion de documentos.",
            }
        )

        with patch("apps.document_extractor.services.get_image_service") as image_service:
            with self.assertRaises(DocumentExtractionError) as ctx:
                DocumentExtractionService(
                    client=client,
                    platform_client=platform_client,
                ).extract_from_upload(
                    request_obj=request_obj,
                    image_file=image,
                )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.message, "Tu plan no incluye extraccion de documentos.")
        self.assertEqual(ctx.exception.payload["code"], "feature_not_enabled")
        self.assertEqual(client.calls, 0)
        image_service.assert_not_called()
        self.assertEqual(DocumentExtraction.objects.count(), 0)

    def test_platform_timeout_is_controlled_and_blocks_before_ai(self):
        tenant_id = uuid.uuid4()
        request_obj = SimpleNamespace(tenant_id=tenant_id)
        image = SimpleUploadedFile("invoice.jpg", b"image-bytes", content_type="image/jpeg")
        client = FakeClient({"status": "completed", "products": []})
        platform_client = FakePlatformClient(
            entitlement_error=PlatformBillingError("Timeout", status_code=504)
        )

        with self.assertRaises(DocumentExtractionError) as ctx:
            DocumentExtractionService(
                client=client,
                platform_client=platform_client,
            ).extract_from_upload(
                request_obj=request_obj,
                image_file=image,
            )

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.payload["code"], "billing_service_unavailable")
        self.assertEqual(client.calls, 0)
        self.assertEqual(DocumentExtraction.objects.count(), 0)

    def test_duplicate_usage_response_does_not_fail_completed_extraction(self):
        tenant_id = uuid.uuid4()
        request_obj = SimpleNamespace(tenant_id=tenant_id)
        image = SimpleUploadedFile("invoice.jpg", b"image-bytes", content_type="image/jpeg")
        platform_client = FakePlatformClient(
            consume_error=PlatformBillingError(
                "Uso ya registrado",
                status_code=409,
                response_data={"duplicate": True},
            )
        )
        client = FakeClient(
            {
                "status": "completed",
                "confidence": 0.95,
                "products": [{"description": "Cafe", "quantity": 1}],
                "usage": {"provider": "mock", "model": "mock-v1"},
            }
        )

        with patch("apps.document_extractor.services.get_image_service", return_value=FakeImageService()):
            extraction = DocumentExtractionService(
                client=client,
                platform_client=platform_client,
            ).extract_from_upload(
                request_obj=request_obj,
                image_file=image,
            )

        extraction.refresh_from_db()
        self.assertEqual(extraction.status, DocumentExtractionStatus.COMPLETED)
        self.assertEqual(len(platform_client.consume_calls), 1)
        self.assertEqual(
            platform_client.consume_calls[0]["idempotency_key"],
            f"document-extraction:{extraction.uuid}",
        )

    def test_idempotent_usage_replay_response_does_not_fail_completed_extraction(self):
        tenant_id = uuid.uuid4()
        request_obj = SimpleNamespace(tenant_id=tenant_id)
        image = SimpleUploadedFile("invoice.jpg", b"image-bytes", content_type="image/jpeg")
        platform_client = FakePlatformClient(
            consume_response={
                "allowed": True,
                "recorded": False,
                "already_recorded": True,
                "feature_key": "document_extraction",
                "period_key": "2026-06",
                "used": 1,
                "limit": 100,
                "remaining": 99,
            }
        )
        client = FakeClient(
            {
                "status": "completed",
                "confidence": 0.95,
                "products": [{"description": "Cafe", "quantity": 1}],
                "usage": {"provider": "mock", "model": "mock-v1"},
            }
        )

        with patch("apps.document_extractor.services.get_image_service", return_value=FakeImageService()):
            extraction = DocumentExtractionService(
                client=client,
                platform_client=platform_client,
            ).extract_from_upload(
                request_obj=request_obj,
                image_file=image,
            )

        extraction.refresh_from_db()
        self.assertEqual(extraction.status, DocumentExtractionStatus.COMPLETED)
        self.assertEqual(len(platform_client.consume_calls), 1)

    def test_usage_registration_error_marks_extraction_failed(self):
        tenant_id = uuid.uuid4()
        request_obj = SimpleNamespace(tenant_id=tenant_id)
        image = SimpleUploadedFile("invoice.jpg", b"image-bytes", content_type="image/jpeg")
        platform_client = FakePlatformClient(
            consume_error=PlatformBillingError(
                "Plataforma no disponible",
                status_code=502,
                response_data={"detail": "upstream unavailable"},
            )
        )
        client = FakeClient(
            {
                "status": "completed",
                "confidence": 0.9,
                "products": [{"description": "Azucar", "quantity": 1}],
                "usage": {"provider": "mock", "model": "mock-v1"},
            }
        )

        with patch("apps.document_extractor.services.get_image_service", return_value=FakeImageService()):
            with self.assertRaises(DocumentExtractionError) as ctx:
                DocumentExtractionService(
                    client=client,
                    platform_client=platform_client,
                ).extract_from_upload(
                    request_obj=request_obj,
                    image_file=image,
                )

        extraction = ctx.exception.extraction
        self.assertIsNotNone(extraction)
        extraction.refresh_from_db()
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.payload["code"], "billing_service_unavailable")
        self.assertEqual(
            ctx.exception.message,
            "No se pudo registrar el consumo del plan. Intenta nuevamente.",
        )
        self.assertEqual(extraction.status, DocumentExtractionStatus.FAILED)
        self.assertEqual(extraction.error_message, ctx.exception.message)
        self.assertEqual(client.calls, 1)
        self.assertEqual(len(platform_client.consume_calls), 1)

    def test_unconfirmed_usage_response_marks_extraction_failed(self):
        tenant_id = uuid.uuid4()
        request_obj = SimpleNamespace(tenant_id=tenant_id)
        image = SimpleUploadedFile("invoice.jpg", b"image-bytes", content_type="image/jpeg")
        platform_client = FakePlatformClient(
            consume_response={
                "consumed": False,
                "allowed": False,
                "reason": "quota_exceeded",
                "message": "Limite mensual de extracciones alcanzado.",
            }
        )
        client = FakeClient(
            {
                "status": "completed",
                "confidence": 0.9,
                "products": [{"description": "Azucar", "quantity": 1}],
                "usage": {"provider": "mock", "model": "mock-v1"},
            }
        )

        with patch("apps.document_extractor.services.get_image_service", return_value=FakeImageService()):
            with self.assertRaises(DocumentExtractionError) as ctx:
                DocumentExtractionService(
                    client=client,
                    platform_client=platform_client,
                ).extract_from_upload(
                    request_obj=request_obj,
                    image_file=image,
                )

        extraction = ctx.exception.extraction
        self.assertIsNotNone(extraction)
        extraction.refresh_from_db()
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.message, "Limite mensual de extracciones alcanzado.")
        self.assertEqual(extraction.status, DocumentExtractionStatus.FAILED)
        self.assertEqual(extraction.error_message, ctx.exception.message)
        self.assertEqual(client.calls, 1)
        self.assertEqual(len(platform_client.consume_calls), 1)

    def test_explicit_usage_denial_is_not_confirmed_by_usage_id(self):
        tenant_id = uuid.uuid4()
        request_obj = SimpleNamespace(tenant_id=tenant_id)
        image = SimpleUploadedFile("invoice.jpg", b"image-bytes", content_type="image/jpeg")
        platform_client = FakePlatformClient(
            consume_response={
                "consumed": False,
                "allowed": False,
                "reason": "quota_exceeded",
                "usage_id": str(uuid.uuid4()),
                "message": "Limite mensual de extracciones alcanzado.",
            }
        )
        client = FakeClient(
            {
                "status": "completed",
                "confidence": 0.9,
                "products": [{"description": "Azucar", "quantity": 1}],
                "usage": {"provider": "mock", "model": "mock-v1"},
            }
        )

        with patch("apps.document_extractor.services.get_image_service", return_value=FakeImageService()):
            with self.assertRaises(DocumentExtractionError) as ctx:
                DocumentExtractionService(
                    client=client,
                    platform_client=platform_client,
                ).extract_from_upload(
                    request_obj=request_obj,
                    image_file=image,
                )

        extraction = ctx.exception.extraction
        self.assertIsNotNone(extraction)
        extraction.refresh_from_db()
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(extraction.status, DocumentExtractionStatus.FAILED)

    def test_explicit_nested_usage_denial_is_not_confirmed_by_nested_usage_id(self):
        tenant_id = uuid.uuid4()
        request_obj = SimpleNamespace(tenant_id=tenant_id)
        image = SimpleUploadedFile("invoice.jpg", b"image-bytes", content_type="image/jpeg")
        platform_client = FakePlatformClient(
            consume_response={
                "usage": {
                    "id": str(uuid.uuid4()),
                    "consumed": False,
                },
                "message": "Consumo no registrado.",
            }
        )
        client = FakeClient(
            {
                "status": "completed",
                "confidence": 0.9,
                "products": [{"description": "Azucar", "quantity": 1}],
                "usage": {"provider": "mock", "model": "mock-v1"},
            }
        )

        with patch("apps.document_extractor.services.get_image_service", return_value=FakeImageService()):
            with self.assertRaises(DocumentExtractionError) as ctx:
                DocumentExtractionService(
                    client=client,
                    platform_client=platform_client,
                ).extract_from_upload(
                    request_obj=request_obj,
                    image_file=image,
                )

        extraction = ctx.exception.extraction
        self.assertIsNotNone(extraction)
        extraction.refresh_from_db()
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(extraction.status, DocumentExtractionStatus.FAILED)

    def test_entitlement_resource_count_uses_only_usable_monthly_extractions(self):
        tenant_id = uuid.uuid4()
        request_obj = SimpleNamespace(tenant_id=tenant_id)
        image = SimpleUploadedFile("invoice.jpg", b"image-bytes", content_type="image/jpeg")
        DocumentExtraction.objects.create(
            tenant_id=tenant_id,
            status=DocumentExtractionStatus.COMPLETED,
        )
        DocumentExtraction.objects.create(
            tenant_id=tenant_id,
            status=DocumentExtractionStatus.NEEDS_REVIEW,
        )
        DocumentExtraction.objects.create(
            tenant_id=tenant_id,
            status=DocumentExtractionStatus.FAILED,
        )
        platform_client = FakePlatformClient()
        client = FakeClient(
            {
                "status": "completed",
                "confidence": 0.9,
                "products": [{"description": "Azucar", "quantity": 1}],
                "usage": {"provider": "mock", "model": "mock-v1"},
            }
        )

        with patch("apps.document_extractor.services.get_image_service", return_value=FakeImageService()):
            DocumentExtractionService(
                client=client,
                platform_client=platform_client,
            ).extract_from_upload(
                request_obj=request_obj,
                image_file=image,
            )

        self.assertEqual(platform_client.entitlement_calls[0]["resource_count"], 2)

    def test_ai_error_marks_extraction_failed(self):
        class FailingClient:
            def __init__(self):
                self.calls = 0

            def extract(self, payload):
                self.calls += 1
                raise DocumentExtractionError("IA fuera de servicio", status_code=502)

        tenant_id = uuid.uuid4()
        request_obj = SimpleNamespace(tenant_id=tenant_id)
        image = SimpleUploadedFile("invoice.png", b"image-bytes", content_type="image/png")
        platform_client = FakePlatformClient()
        client = FailingClient()

        with patch("apps.document_extractor.services.get_image_service", return_value=FakeImageService()):
            with self.assertRaises(DocumentExtractionError) as ctx:
                DocumentExtractionService(
                    client=client,
                    platform_client=platform_client,
                ).extract_from_upload(
                    request_obj=request_obj,
                    image_file=image,
                )

        extraction = ctx.exception.extraction
        self.assertIsNotNone(extraction)
        extraction.refresh_from_db()
        self.assertEqual(extraction.status, DocumentExtractionStatus.FAILED)
        self.assertEqual(extraction.error_message, "IA fuera de servicio")
        self.assertEqual(client.calls, 1)
        self.assertEqual(platform_client.consume_calls, [])


class AIExtractorClientTests(TestCase):
    @override_settings(
        AI_EXTRACTOR_BASE_URL="http://ia.local/api/v1",
        AI_EXTRACTOR_TOKEN="secret-token",
        AI_EXTRACTOR_SOURCE="postas_api",
        AI_EXTRACTOR_TIMEOUT=10,
    )
    def test_client_sends_token_and_source_to_ai_api(self):
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"status": "processed", "products": []}'

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["authorization"] = req.get_header("Authorization")
            captured["source"] = req.get_header("X-postas-source")
            captured["timeout"] = timeout
            return Response()

        with patch("apps.document_extractor.services.request.urlopen", side_effect=fake_urlopen):
            response = AIExtractorClient().extract({"tenant_id": "tenant", "signed_image_url": "url"})

        self.assertEqual(response["status"], "processed")
        self.assertEqual(captured["url"], "http://ia.local/api/v1/document-extractions/process")
        self.assertEqual(captured["authorization"], "Bearer secret-token")
        self.assertEqual(captured["source"], "postas_api")
        self.assertEqual(captured["timeout"], 10)
