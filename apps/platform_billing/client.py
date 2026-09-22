import json
import threading
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib import parse

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter


class PlatformBillingError(Exception):
    def __init__(self, message: str, *, status_code: int = 503, response_data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_data = response_data or {}


_shared_session: requests.Session | None = None
_shared_session_lock = threading.Lock()


def _get_shared_session() -> requests.Session:
    global _shared_session
    if _shared_session is None:
        with _shared_session_lock:
            if _shared_session is None:
                session = requests.Session()
                adapter = HTTPAdapter(
                    pool_connections=settings.POSTAS_PLATFORM_POOL_CONNECTIONS,
                    pool_maxsize=settings.POSTAS_PLATFORM_POOL_MAXSIZE,
                    max_retries=0,
                    pool_block=True,
                )
                session.mount("http://", adapter)
                session.mount("https://", adapter)
                _shared_session = session
    return _shared_session


class PlatformBillingClient:
    def __init__(self, *, base_url: str | None = None, service_token: str | None = None, source: str | None = None, timeout: int | float | None = None, session: requests.Session | None = None) -> None:
        self.base_url = (base_url or settings.POSTAS_PLATFORM_API_URL).rstrip("/")
        self.service_token = service_token if service_token is not None else settings.POSTAS_PLATFORM_SERVICE_TOKEN
        self.source = source if source is not None else settings.POSTAS_PLATFORM_SOURCE
        self.timeout = timeout or settings.POSTAS_PLATFORM_TIMEOUT_SECONDS
        self.session = session or _get_shared_session()

    def get_tenant_status(self, tenant_id) -> dict[str, Any]:
        tenant = parse.quote(str(tenant_id), safe="")
        return self._request("GET", f"/internal/v1/tenants/{tenant}/status")

    def check_entitlement(self, tenant_id, feature_key: str, *, amount: int = 1, resource_count: int | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"tenant_id": str(tenant_id), "feature_key": feature_key, "amount": amount}
        if resource_count is not None:
            payload["resource_count"] = resource_count
        if context is not None:
            payload["context"] = context
        return self._request("POST", "/internal/v1/entitlements/check", payload)

    def consume_usage(self, tenant_id, feature_key: str, *, amount: int = 1, external_id=None, idempotency_key: str | None = None, occurred_at=None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = self._usage_payload(tenant_id=tenant_id, feature_key=feature_key, amount=amount, external_id=external_id, idempotency_key=idempotency_key, occurred_at=occurred_at, metadata=metadata)
        return self._request("POST", "/internal/v1/usage/consume", payload)

    def check_and_consume(self, tenant_id, feature_key: str, *, amount: int = 1, resource_count: int | None = None, external_id=None, idempotency_key: str | None = None, occurred_at=None, metadata: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = self._usage_payload(tenant_id=tenant_id, feature_key=feature_key, amount=amount, external_id=external_id, idempotency_key=idempotency_key, occurred_at=occurred_at, metadata=metadata)
        if resource_count is not None:
            payload["resource_count"] = resource_count
        if context is not None:
            payload["context"] = context
        return self._request("POST", "/internal/v1/usage/check-and-consume", payload)

    def reserve_usage(
        self, tenant_id, feature_key: str, *, amount: int, external_id,
        idempotency_key: str, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request("POST", "/internal/v1/billing/reservations/reserve", {
            "tenant_id": str(tenant_id), "feature_key": feature_key,
            "amount": amount, "external_id": str(external_id),
            "idempotency_key": idempotency_key, "metadata": metadata or {},
        })

    def commit_usage_reservation(self, tenant_id, *, idempotency_key: str) -> dict[str, Any]:
        return self._request("POST", "/internal/v1/billing/reservations/commit", {
            "tenant_id": str(tenant_id), "feature_key": "pos_sales",
            "idempotency_key": idempotency_key,
        })

    def release_usage_reservation(self, tenant_id, *, idempotency_key: str) -> dict[str, Any]:
        return self._request("POST", "/internal/v1/billing/reservations/release", {
            "tenant_id": str(tenant_id), "feature_key": "pos_sales",
            "idempotency_key": idempotency_key,
        })

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self._validate_configuration()
        body = None
        if payload is not None:
            body = json.dumps(payload, default=_json_default).encode("utf-8")

        headers = self._headers(has_body=payload is not None)
        if extra_headers:
            headers.update(extra_headers)
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                data=body,
                headers=headers,
                timeout=self.timeout,
                verify=True,
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise PlatformBillingError("Timeout consultando postas_platform_api.", status_code=504) from exc
        except requests.exceptions.HTTPError as exc:
            error_response = exc.response
            if error_response is None:
                raise PlatformBillingError(
                    "postas_platform_api devolvio un error HTTP sin respuesta.",
                    status_code=502,
                ) from exc
            response_data = self._parse_error_body(error_response)
            raise PlatformBillingError(
                self._error_message(error_response.status_code, response_data),
                status_code=error_response.status_code,
                response_data=response_data,
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise PlatformBillingError(f"No se pudo conectar con postas_platform_api: {exc}", status_code=503) from exc

        try:
            parsed = response.json() if response.content else {}
        except (requests.exceptions.JSONDecodeError, ValueError) as exc:
            raise PlatformBillingError("postas_platform_api devolvio una respuesta JSON invalida.", status_code=502) from exc
        if not isinstance(parsed, dict):
            raise PlatformBillingError("postas_platform_api devolvio un formato inesperado.", status_code=502)
        return parsed

    def _headers(self, *, has_body: bool) -> dict[str, str]:
        headers = {"Accept": "application/json", "X-Postas-Source": self.source, "X-Postas-Service-Token": self.service_token}
        if has_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _validate_configuration(self) -> None:
        if not self.base_url:
            raise PlatformBillingError("POSTAS_PLATFORM_API_URL no esta configurado.", status_code=503)
        if not self.service_token:
            raise PlatformBillingError("POSTAS_PLATFORM_SERVICE_TOKEN no esta configurado.", status_code=503)
        if settings.POSTAS_PLATFORM_REQUIRE_TLS and parse.urlparse(self.base_url).scheme.lower() != "https":
            raise PlatformBillingError("POSTAS_PLATFORM_API_URL debe usar HTTPS.", status_code=503)

    @staticmethod
    def _usage_payload(*, tenant_id, feature_key: str, amount: int, external_id, idempotency_key: str | None, occurred_at, metadata: dict[str, Any] | None) -> dict[str, Any]:
        payload: dict[str, Any] = {"tenant_id": str(tenant_id), "feature_key": feature_key, "amount": amount}
        if external_id is not None:
            payload["external_id"] = str(external_id)
        if idempotency_key is not None:
            payload["idempotency_key"] = idempotency_key
        if occurred_at is not None:
            payload["occurred_at"] = occurred_at.isoformat() if hasattr(occurred_at, "isoformat") else str(occurred_at)
        if metadata is not None:
            payload["metadata"] = metadata
        return payload

    @staticmethod
    def _parse_error_body(response: requests.Response) -> dict[str, Any]:
        try:
            parsed = response.json() if response.content else {}
        except (requests.exceptions.JSONDecodeError, ValueError):
            return {"detail": response.text}
        return parsed if isinstance(parsed, dict) else {"detail": response.text}

    @staticmethod
    def _error_message(status_code: int, response_data: dict[str, Any]) -> str:
        detail = response_data.get("detail") or response_data.get("error") or response_data.get("message") or response_data.get("reason")
        return str(detail) if detail else f"postas_platform_api respondio con HTTP {status_code}."


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
