import logging
import threading
from typing import Any

from django.conf import settings
from django.core.cache import cache
from rest_framework import status
from rest_framework.exceptions import APIException

from .client import PlatformBillingClient, PlatformBillingError


logger = logging.getLogger(__name__)


SUBSCRIPTION_PAYMENT_CODES = {
    "subscription_not_found",
    "subscription_expired",
    "subscription_cancelled",
    "subscription_payment_required",
    "subscription_inactive",
}
FEATURE_DENIED_CODES = {"feature_not_enabled"}
LIMIT_DENIED_CODES = {"quota_exceeded", "resource_limit_exceeded"}
BUSINESS_DENIED_CODES = SUBSCRIPTION_PAYMENT_CODES | FEATURE_DENIED_CODES | LIMIT_DENIED_CODES
CACHEABLE_DENIED_CODES = SUBSCRIPTION_PAYMENT_CODES | FEATURE_DENIED_CODES
PLATFORM_UNAVAILABLE_CODE = "billing_service_unavailable"
CACHEABLE_ENTITLEMENT_FEATURES = frozenset({"basic_reports", "advanced_reports"})

_default_client = None
_default_client_factory = None
_default_client_lock = threading.Lock()


class BillingEnforcementError(APIException):
    default_code = "billing_enforcement_failed"

    def __init__(self, payload: dict[str, Any], status_code: int) -> None:
        self.status_code = status_code
        self.payload = payload
        self.detail = payload


def reserve_billing_usage(
    tenant_id, feature_key: str, *, amount: int, external_id,
    idempotency_key: str, metadata=None, client=None,
):
    billing_client = client or PlatformBillingClient()
    try:
        response = billing_client.reserve_usage(
            tenant_id, feature_key, amount=amount, external_id=external_id,
            idempotency_key=idempotency_key, metadata=metadata,
        )
    except PlatformBillingError as exc:
        if exc.status_code == status.HTTP_409_CONFLICT and _is_duplicate_usage_response(exc.response_data):
            return exc.response_data
        raise _platform_unavailable(feature_key, exc, detail="No se pudo reservar el consumo del plan.") from exc
    if response.get("allowed") is False or response.get("status") == "released":
        return _assert_allowed_response(response, feature_key)
    if (
        response.get("status") in {"active", "committed"}
        and (response.get("reservation_id") or response.get("id"))
    ):
        return response
    raise BillingEnforcementError(
        _stable_payload(feature_key=feature_key, code=PLATFORM_UNAVAILABLE_CODE,
                        detail="La plataforma no confirmo la reserva del consumo."),
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def commit_billing_reservation(tenant_id, *, idempotency_key: str, client=None):
    return _change_billing_reservation(
        tenant_id, idempotency_key=idempotency_key, operation="commit", client=client,
    )


def release_billing_reservation(tenant_id, *, idempotency_key: str, client=None):
    return _change_billing_reservation(
        tenant_id, idempotency_key=idempotency_key, operation="release", client=client,
    )


def _change_billing_reservation(tenant_id, *, idempotency_key, operation, client=None):
    billing_client = client or PlatformBillingClient()
    try:
        method = (billing_client.commit_usage_reservation if operation == "commit"
                  else billing_client.release_usage_reservation)
        response = method(tenant_id, idempotency_key=idempotency_key)
    except PlatformBillingError as exc:
        if (
            operation == "release"
            and exc.status_code == status.HTTP_409_CONFLICT
            and _platform_error_code(exc.response_data) == "reservation_not_found"
        ):
            return {
                "allowed": True,
                "status": "released",
                "released": True,
                "already_applied": True,
            }
        if exc.status_code == status.HTTP_409_CONFLICT and _is_duplicate_usage_response(exc.response_data):
            return exc.response_data
        raise _platform_unavailable(
            "pos_sales", exc, detail=f"No se pudo {operation} la reserva del plan.",
        ) from exc
    positive = (
        response.get("committed") is True or response.get("released") is True
        or response.get("already_committed") is True or response.get("already_released") is True
        or response.get("status") in {"committed", "released"}
    )
    if not positive:
        raise BillingEnforcementError(
            _stable_payload(feature_key="pos_sales", code=PLATFORM_UNAVAILABLE_CODE,
                            detail=f"La plataforma no confirmo {operation} de la reserva."),
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return response


def check_billing_entitlement(
    tenant_id,
    feature_key: str,
    *,
    amount: int = 1,
    resource_count: int | None = None,
    context: dict[str, Any] | None = None,
    client: PlatformBillingClient | None = None,
) -> dict[str, Any]:
    cacheable = (
        feature_key in CACHEABLE_ENTITLEMENT_FEATURES
        and amount == 1
        and resource_count is None
    )
    cache_key = _entitlement_cache_key(tenant_id, feature_key)
    if cacheable:
        cached_response = _cache_get(cache_key)
        if cached_response is not None:
            return _assert_allowed_response(cached_response, feature_key)

    billing_client = client or _get_default_client()
    try:
        response = billing_client.check_entitlement(
            tenant_id,
            feature_key,
            amount=amount,
            resource_count=resource_count,
            context=context,
        )
    except PlatformBillingError as exc:
        raise _platform_unavailable(feature_key, exc) from exc

    if cacheable and _is_cacheable_response(response):
        timeout = (
            settings.BILLING_ENTITLEMENT_ALLOW_TTL_SECONDS
            if response.get("allowed") is True
            else settings.BILLING_ENTITLEMENT_DENY_TTL_SECONDS
        )
        _cache_set(cache_key, response, timeout)
    return _assert_allowed_response(response, feature_key)


def check_and_consume_billing_usage(
    tenant_id,
    feature_key: str,
    *,
    amount: int = 1,
    resource_count: int | None = None,
    external_id=None,
    idempotency_key: str,
    occurred_at=None,
    metadata: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    client: PlatformBillingClient | None = None,
) -> dict[str, Any]:
    billing_client = client or _get_default_client()
    try:
        response = billing_client.check_and_consume(
            tenant_id,
            feature_key,
            amount=amount,
            resource_count=resource_count,
            external_id=external_id,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            metadata=metadata,
            context=context,
        )
    except PlatformBillingError as exc:
        if exc.status_code == status.HTTP_409_CONFLICT and _is_duplicate_usage_response(exc.response_data):
            return exc.response_data
        raise _platform_unavailable(
            feature_key,
            exc,
            detail="No se pudo registrar el consumo del plan. Intenta nuevamente.",
        ) from exc

    response = _assert_allowed_response(response, feature_key)
    if _is_confirmed_usage_response(response):
        return response
    raise BillingEnforcementError(
        _stable_payload(
            feature_key=feature_key,
            code=PLATFORM_UNAVAILABLE_CODE,
            detail="La plataforma de billing no confirmo el registro del consumo.",
        ),
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _assert_allowed_response(response: dict[str, Any], feature_key: str) -> dict[str, Any]:
    if response.get("allowed") is True:
        return response
    if response.get("allowed") is False:
        code = _response_code(response)
        if code in BUSINESS_DENIED_CODES:
            raise BillingEnforcementError(
                _stable_payload(
                    feature_key=feature_key,
                    code=code,
                    detail=_response_detail(response, code),
                    limit=response.get("limit"),
                    used=response.get("used"),
                    remaining=response.get("remaining"),
                    upgrade_required=_upgrade_required(response, code),
                ),
                _status_for_code(code),
            )
    raise BillingEnforcementError(
        _stable_payload(
            feature_key=feature_key,
            code=PLATFORM_UNAVAILABLE_CODE,
            detail="La plataforma de billing no confirmo el permiso solicitado.",
        ),
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _platform_unavailable(
    feature_key: str,
    exc: PlatformBillingError,
    *,
    detail: str = "No se pudo validar el plan del tenant.",
) -> BillingEnforcementError:
    logger.warning(
        "Platform billing enforcement failed: feature=%s status=%s error_type=%s",
        feature_key,
        exc.status_code,
        type(exc).__name__,
    )
    return BillingEnforcementError(
        _stable_payload(
            feature_key=feature_key,
            code=PLATFORM_UNAVAILABLE_CODE,
            detail=detail,
        ),
        status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def _stable_payload(
    *,
    feature_key: str,
    code: str,
    detail: str,
    limit: int | None = None,
    used: int | None = None,
    remaining: int | None = None,
    upgrade_required: bool = False,
) -> dict[str, Any]:
    return {
        "detail": detail,
        "code": code,
        "feature_key": feature_key,
        "limit": limit,
        "used": used,
        "remaining": remaining,
        "upgrade_required": upgrade_required,
    }


def _status_for_code(code: str) -> int:
    if code in SUBSCRIPTION_PAYMENT_CODES:
        return status.HTTP_402_PAYMENT_REQUIRED
    if code in FEATURE_DENIED_CODES:
        return status.HTTP_403_FORBIDDEN
    if code in LIMIT_DENIED_CODES:
        return status.HTTP_429_TOO_MANY_REQUESTS
    return status.HTTP_503_SERVICE_UNAVAILABLE


def _response_code(response: dict[str, Any]) -> str:
    return str(
        response.get("code")
        or response.get("reason")
        or response.get("error_code")
        or response.get("error")
        or ""
    )


def _platform_error_code(response: dict[str, Any]) -> str:
    detail = response.get("detail")
    if isinstance(detail, dict) and detail.get("code"):
        return str(detail["code"]).lower()
    return _response_code(response).lower()


def _response_detail(response: dict[str, Any], code: str) -> str:
    detail = (
        response.get("detail")
        or response.get("message")
        or response.get("error")
        or response.get("reason")
        or code
    )
    return str(detail)


def _upgrade_required(response: dict[str, Any], code: str) -> bool:
    return bool(response.get("upgrade_required") or code in BUSINESS_DENIED_CODES)


def _is_confirmed_usage_response(response: dict[str, Any]) -> bool:
    if _is_duplicate_usage_response(response):
        return True
    if _has_explicit_usage_denial(response):
        return False
    if response.get("recorded") is True:
        return True
    if response.get("already_recorded") is True:
        return True
    if response.get("consumed") is True:
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


def _is_duplicate_usage_response(data: dict[str, Any]) -> bool:
    code = str(data.get("code") or data.get("error_code") or "").lower()
    detail = str(data.get("detail") or data.get("message") or data.get("error") or "").lower()
    status_value = str(data.get("status") or "").lower()
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
        or status_value in {"duplicate", "already_consumed", "idempotent_replay"}
        or ("idempotency" in detail and "duplicate" in detail)
        or ("already" in detail and "consum" in detail)
        or ("already" in detail and "record" in detail)
    )


def _get_default_client() -> PlatformBillingClient:
    global _default_client, _default_client_factory
    if _default_client is None or _default_client_factory is not PlatformBillingClient:
        with _default_client_lock:
            if _default_client is None or _default_client_factory is not PlatformBillingClient:
                _default_client = PlatformBillingClient()
                _default_client_factory = PlatformBillingClient
    return _default_client


def _entitlement_cache_key(tenant_id, feature_key: str) -> str:
    return f"billing:entitlement:v1:{tenant_id}:{feature_key}"


def _is_cacheable_response(response: dict[str, Any]) -> bool:
    if not isinstance(response, dict):
        return False
    if response.get("allowed") is True:
        return True
    return response.get("allowed") is False and _response_code(response) in CACHEABLE_DENIED_CODES


def _cache_get(key: str):
    try:
        value = cache.get(key)
    except Exception as exc:
        logger.warning("Billing entitlement cache read failed: %s", type(exc).__name__)
        return None
    return value if _is_cacheable_response(value) else None


def _cache_set(key: str, value: dict[str, Any], timeout: int) -> None:
    try:
        cache.set(key, value, timeout=timeout)
    except Exception as exc:
        logger.warning("Billing entitlement cache write failed: %s", type(exc).__name__)
