import logging
from typing import Any

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
PLATFORM_UNAVAILABLE_CODE = "billing_service_unavailable"


class BillingEnforcementError(APIException):
    default_code = "billing_enforcement_failed"

    def __init__(self, payload: dict[str, Any], status_code: int) -> None:
        self.status_code = status_code
        self.payload = payload
        self.detail = payload


def check_billing_entitlement(
    tenant_id,
    feature_key: str,
    *,
    amount: int = 1,
    resource_count: int | None = None,
    context: dict[str, Any] | None = None,
    client: PlatformBillingClient | None = None,
) -> dict[str, Any]:
    billing_client = client or PlatformBillingClient()
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
    billing_client = client or PlatformBillingClient()
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
        "Platform billing enforcement failed: feature=%s status=%s detail=%s response=%s",
        feature_key,
        exc.status_code,
        exc.message,
        exc.response_data,
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
