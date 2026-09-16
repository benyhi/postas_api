import hashlib
import hmac

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.mercado_pago.models import MercadoPagoWebhookInbox
from apps.mercado_pago.serializers import WebhookReceiptSerializer


class MercadoPagoOrdersWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Mercado Pago Webhooks"], summary="Recibir notificaciones de orders",
        auth=[], request=None, responses={200: WebhookReceiptSerializer, 401: None},
    )
    def post(self, request):
        data_id = str(request.query_params.get("data.id") or "")
        request_id = str(request.headers.get("X-Request-Id") or "")
        signature = str(request.headers.get("X-Signature") or "")
        if not _valid_signature(
            secret=settings.MERCADO_PAGO_WEBHOOK_SECRET,
            signature=signature,
            request_id=request_id,
            data_id=data_id,
            tolerance_seconds=settings.MERCADO_PAGO_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS,
        ):
            return Response({"detail": "Invalid Mercado Pago signature."}, status=401)
        payload = request.data if isinstance(request.data, dict) else {}
        topic = str(payload.get("type") or request.query_params.get("type") or "")
        action = str(payload.get("action") or request.query_params.get("action") or "")
        notification_id = payload.get("id")
        stable_notification = (
            f"notification:{notification_id}"
            if notification_id
            else f"order:{data_id}:{action}:{payload.get('date_created') or ''}"
        )
        notification_key = hashlib.sha256(stable_notification.encode("utf-8")).hexdigest()
        MercadoPagoWebhookInbox.objects.get_or_create(
            notification_key=notification_key,
            defaults={
                "request_id": request_id,
                "data_id": data_id,
                "topic": topic,
                "action": action,
                "payload": payload,
                "next_attempt_at": timezone.now(),
            },
        )
        return Response({"received": True})


def _valid_signature(*, secret, signature, request_id, data_id, tolerance_seconds):
    if not secret or not signature or not request_id or not data_id:
        return False
    parts = {}
    for part in signature.split(","):
        key, separator, value = part.strip().partition("=")
        if separator:
            parts[key] = value
    timestamp = parts.get("ts")
    supplied = parts.get("v1")
    if not timestamp or not supplied:
        return False
    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(timezone.now().timestamp()) - timestamp_value) > max(0, tolerance_seconds):
        return False
    manifest = f"id:{data_id};request-id:{request_id};ts:{timestamp};"
    expected = hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)
