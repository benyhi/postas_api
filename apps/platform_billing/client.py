import json
import socket
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib import error, parse, request

from django.conf import settings


class PlatformBillingError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 503,
        response_data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_data = response_data or {}


class PlatformBillingClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        service_token: str | None = None,
        source: str | None = None,
        timeout: int | float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.POSTAS_PLATFORM_API_URL).rstrip("/")
        self.service_token = (
            service_token
            if service_token is not None
            else settings.POSTAS_PLATFORM_SERVICE_TOKEN
        )
        self.source = source if source is not None else settings.POSTAS_PLATFORM_SOURCE
        self.timeout = timeout or settings.POSTAS_PLATFORM_TIMEOUT_SECONDS

    def get_tenant_status(self, tenant_id) -> dict[str, Any]:
        tenant = parse.quote(str(tenant_id), safe="")
        return self._request("GET", f"/internal/v1/tenants/{tenant}/status")

    def check_entitlement(
        self,
        tenant_id,
        feature_key: str,
        *,
        amount: int = 1,
        resource_count: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "feature_key": feature_key,
            "amount": amount,
        }
        if resource_count is not None:
            payload["resource_count"] = resource_count
        if context is not None:
            payload["context"] = context
        return self._request("POST", "/internal/v1/entitlements/check", payload)

    def consume_usage(
        self,
        tenant_id,
        feature_key: str,
        *,
        amount: int = 1,
        external_id=None,
        idempotency_key: str | None = None,
        occurred_at=None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self._usage_payload(
            tenant_id=tenant_id,
            feature_key=feature_key,
            amount=amount,
            external_id=external_id,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            metadata=metadata,
        )
        return self._request("POST", "/internal/v1/usage/consume", payload)

    def check_and_consume(
        self,
        tenant_id,
        feature_key: str,
        *,
        amount: int = 1,
        resource_count: int | None = None,
        external_id=None,
        idempotency_key: str | None = None,
        occurred_at=None,
        metadata: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self._usage_payload(
            tenant_id=tenant_id,
            feature_key=feature_key,
            amount=amount,
            external_id=external_id,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            metadata=metadata,
        )
        if resource_count is not None:
            payload["resource_count"] = resource_count
        if context is not None:
            payload["context"] = context
        return self._request("POST", "/internal/v1/usage/check-and-consume", payload)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._validate_configuration()
        body = None
        if payload is not None:
            body = json.dumps(payload, default=_json_default).encode("utf-8")

        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=self._headers(has_body=payload is not None),
            method=method,
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            response_data = self._parse_error_body(exc)
            raise PlatformBillingError(
                self._error_message(exc, response_data),
                status_code=exc.code,
                response_data=response_data,
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise PlatformBillingError(
                "Timeout consultando postas_platform_api.",
                status_code=504,
            ) from exc
        except error.URLError as exc:
            if isinstance(exc.reason, TimeoutError | socket.timeout):
                raise PlatformBillingError(
                    "Timeout consultando postas_platform_api.",
                    status_code=504,
                ) from exc
            raise PlatformBillingError(
                f"No se pudo conectar con postas_platform_api: {exc.reason}",
                status_code=503,
            ) from exc

        try:
            parsed = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError as exc:
            raise PlatformBillingError(
                "postas_platform_api devolvio una respuesta JSON invalida.",
                status_code=502,
            ) from exc
        if not isinstance(parsed, dict):
            raise PlatformBillingError(
                "postas_platform_api devolvio un formato inesperado.",
                status_code=502,
            )
        return parsed

    def _headers(self, *, has_body: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "X-Postas-Source": self.source,
            "X-Postas-Service-Token": self.service_token,
        }
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _validate_configuration(self) -> None:
        if not self.base_url:
            raise PlatformBillingError(
                "POSTAS_PLATFORM_API_URL no esta configurado.",
                status_code=503,
            )
        if not self.service_token:
            raise PlatformBillingError(
                "POSTAS_PLATFORM_SERVICE_TOKEN no esta configurado.",
                status_code=503,
            )

    @staticmethod
    def _usage_payload(
        *,
        tenant_id,
        feature_key: str,
        amount: int,
        external_id,
        idempotency_key: str | None,
        occurred_at,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "feature_key": feature_key,
            "amount": amount,
        }
        if external_id is not None:
            payload["external_id"] = str(external_id)
        if idempotency_key is not None:
            payload["idempotency_key"] = idempotency_key
        if occurred_at is not None:
            payload["occurred_at"] = (
                occurred_at.isoformat() if hasattr(occurred_at, "isoformat") else str(occurred_at)
            )
        if metadata is not None:
            payload["metadata"] = metadata
        return payload

    @staticmethod
    def _parse_error_body(exc: error.HTTPError) -> dict[str, Any]:
        raw_body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            return {"detail": raw_body}
        return parsed if isinstance(parsed, dict) else {"detail": raw_body}

    @staticmethod
    def _error_message(exc: error.HTTPError, response_data: dict[str, Any]) -> str:
        detail = (
            response_data.get("detail")
            or response_data.get("error")
            or response_data.get("message")
            or response_data.get("reason")
        )
        if detail:
            return str(detail)
        return f"postas_platform_api respondio con HTTP {exc.code}."


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
