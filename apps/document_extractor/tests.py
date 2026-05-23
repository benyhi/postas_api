import uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

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

    def extract(self, payload):
        self.payload = payload
        return self.response


@override_settings(
    DOCUMENT_EXTRACTOR_MONTHLY_LIMIT=0,
    DOCUMENT_EXTRACTOR_ALLOWED_EXTENSIONS=(".jpg", ".jpeg", ".png"),
    DOCUMENT_EXTRACTOR_MAX_IMAGE_SIZE=1024 * 1024,
    DOCUMENT_EXTRACTOR_PRESIGNED_URL_TTL=300,
)
class DocumentExtractionServiceTests(TestCase):
    def test_extract_from_upload_persists_ai_response_and_usage(self):
        tenant_id = uuid.uuid4()
        request_obj = SimpleNamespace(tenant_id=tenant_id)
        image = SimpleUploadedFile("invoice.jpg", b"image-bytes", content_type="image/jpeg")
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
            extraction = DocumentExtractionService(client=client).extract_from_upload(
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

    def test_ai_error_marks_extraction_failed(self):
        class FailingClient:
            def extract(self, payload):
                raise DocumentExtractionError("IA fuera de servicio", status_code=502)

        tenant_id = uuid.uuid4()
        request_obj = SimpleNamespace(tenant_id=tenant_id)
        image = SimpleUploadedFile("invoice.png", b"image-bytes", content_type="image/png")

        with patch("apps.document_extractor.services.get_image_service", return_value=FakeImageService()):
            with self.assertRaises(DocumentExtractionError) as ctx:
                DocumentExtractionService(client=FailingClient()).extract_from_upload(
                    request_obj=request_obj,
                    image_file=image,
                )

        extraction = ctx.exception.extraction
        self.assertIsNotNone(extraction)
        extraction.refresh_from_db()
        self.assertEqual(extraction.status, DocumentExtractionStatus.FAILED)
        self.assertEqual(extraction.error_message, "IA fuera de servicio")


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
