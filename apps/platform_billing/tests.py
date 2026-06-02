import json
import uuid
from io import BytesIO
from unittest.mock import patch
from urllib import error

from django.test import SimpleTestCase, override_settings

from .client import PlatformBillingClient, PlatformBillingError


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.body).encode("utf-8")


@override_settings(
    POSTAS_PLATFORM_API_URL="http://platform.local",
    POSTAS_PLATFORM_SERVICE_TOKEN="shared-token",
    POSTAS_PLATFORM_SOURCE="postas_api",
    POSTAS_PLATFORM_TIMEOUT_SECONDS=7,
)
class PlatformBillingClientTests(SimpleTestCase):
    def test_check_entitlement_sends_required_headers_and_payload(self):
        tenant_id = uuid.uuid4()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["method"] = req.get_method()
            captured["source"] = req.get_header("X-postas-source")
            captured["token"] = req.get_header("X-postas-service-token")
            captured["content_type"] = req.get_header("Content-type")
            captured["timeout"] = timeout
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return Response({"allowed": True})

        with patch("apps.platform_billing.client.request.urlopen", side_effect=fake_urlopen):
            response = PlatformBillingClient().check_entitlement(
                tenant_id,
                "document_extraction",
                amount=1,
                resource_count=3,
                context={"operation": "extract_from_upload"},
            )

        self.assertEqual(response, {"allowed": True})
        self.assertEqual(captured["url"], "http://platform.local/internal/v1/entitlements/check")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["source"], "postas_api")
        self.assertEqual(captured["token"], "shared-token")
        self.assertEqual(captured["content_type"], "application/json")
        self.assertEqual(captured["timeout"], 7)
        self.assertEqual(captured["payload"]["tenant_id"], str(tenant_id))
        self.assertEqual(captured["payload"]["feature_key"], "document_extraction")
        self.assertEqual(captured["payload"]["resource_count"], 3)

    def test_consume_usage_reuses_stable_idempotency_key(self):
        tenant_id = uuid.uuid4()
        external_id = uuid.uuid4()
        payloads = []

        def fake_urlopen(req, timeout):
            payloads.append(json.loads(req.data.decode("utf-8")))
            return Response({"consumed": False, "duplicate": True})

        client = PlatformBillingClient()
        with patch("apps.platform_billing.client.request.urlopen", side_effect=fake_urlopen):
            first = client.consume_usage(
                tenant_id,
                "document_extraction",
                external_id=external_id,
                idempotency_key=f"document-extraction:{external_id}",
            )
            second = client.consume_usage(
                tenant_id,
                "document_extraction",
                external_id=external_id,
                idempotency_key=f"document-extraction:{external_id}",
            )

        self.assertEqual(first, {"consumed": False, "duplicate": True})
        self.assertEqual(second, {"consumed": False, "duplicate": True})
        self.assertEqual(payloads[0]["idempotency_key"], payloads[1]["idempotency_key"])
        self.assertEqual(payloads[0]["external_id"], str(external_id))

    def test_check_and_consume_sends_required_endpoint_context_and_payload(self):
        tenant_id = uuid.uuid4()
        external_id = uuid.uuid4()
        captured = {}

        def fake_urlopen(req, timeout):
            captured["url"] = req.full_url
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return Response({"allowed": True, "recorded": True})

        with patch("apps.platform_billing.client.request.urlopen", side_effect=fake_urlopen):
            response = PlatformBillingClient().check_and_consume(
                tenant_id,
                "document_extraction",
                amount=1,
                resource_count=2,
                external_id=external_id,
                idempotency_key=f"document-extraction:{external_id}",
                metadata={"provider": "mock"},
                context={"operation": "consume_after_successful_extraction"},
            )

        self.assertEqual(response, {"allowed": True, "recorded": True})
        self.assertEqual(captured["url"], "http://platform.local/internal/v1/usage/check-and-consume")
        self.assertEqual(captured["payload"]["tenant_id"], str(tenant_id))
        self.assertEqual(captured["payload"]["feature_key"], "document_extraction")
        self.assertEqual(captured["payload"]["resource_count"], 2)
        self.assertEqual(captured["payload"]["external_id"], str(external_id))
        self.assertEqual(captured["payload"]["metadata"], {"provider": "mock"})
        self.assertEqual(
            captured["payload"]["context"],
            {"operation": "consume_after_successful_extraction"},
        )

    def test_timeout_raises_controlled_error(self):
        with patch("apps.platform_billing.client.request.urlopen", side_effect=TimeoutError):
            with self.assertRaises(PlatformBillingError) as ctx:
                PlatformBillingClient().get_tenant_status(uuid.uuid4())

        self.assertEqual(ctx.exception.status_code, 504)
        self.assertIn("Timeout", ctx.exception.message)

    def test_http_error_preserves_status_code_message_and_response_data(self):
        body = json.dumps({"detail": "Plan suspendido", "code": "subscription_suspended"}).encode("utf-8")
        http_error = error.HTTPError(
            "http://platform.local/internal/v1/entitlements/check",
            402,
            "Payment Required",
            hdrs=None,
            fp=BytesIO(body),
        )

        with patch("apps.platform_billing.client.request.urlopen", side_effect=http_error):
            with self.assertRaises(PlatformBillingError) as ctx:
                PlatformBillingClient().check_entitlement(
                    uuid.uuid4(),
                    "document_extraction",
                )

        self.assertEqual(ctx.exception.status_code, 402)
        self.assertEqual(ctx.exception.message, "Plan suspendido")
        self.assertEqual(
            ctx.exception.response_data,
            {"detail": "Plan suspendido", "code": "subscription_suspended"},
        )

    @override_settings(POSTAS_PLATFORM_SERVICE_TOKEN="")
    def test_missing_service_token_raises_controlled_error(self):
        with self.assertRaises(PlatformBillingError) as ctx:
            PlatformBillingClient().get_tenant_status(uuid.uuid4())

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("POSTAS_PLATFORM_SERVICE_TOKEN", ctx.exception.message)
