from urllib import parse

from apps.platform_billing.client import PlatformBillingClient


class PlatformMercadoPagoClient(PlatformBillingClient):
    def _tenant_path(self, tenant_id):
        return f"/internal/v1/mercado-pago/tenants/{parse.quote(str(tenant_id), safe='')}"

    def start_oauth(self, tenant_id, payload=None):
        return self._request("POST", f"{self._tenant_path(tenant_id)}/oauth/authorize", payload)

    def get_connection(self, tenant_id):
        return self._request("GET", f"{self._tenant_path(tenant_id)}/connection")

    def delete_connection(self, tenant_id):
        return self._request("DELETE", f"{self._tenant_path(tenant_id)}/connection")

    def list_terminals(self, tenant_id):
        return self._request("GET", f"{self._tenant_path(tenant_id)}/terminals")

    def list_pos(self, tenant_id):
        return self._request("GET", f"{self._tenant_path(tenant_id)}/pos")

    def create_order(self, tenant_id, payload, *, idempotency_key):
        return self._request(
            "POST",
            f"{self._tenant_path(tenant_id)}/orders",
            payload,
            extra_headers={"X-Idempotency-Key": idempotency_key},
        )

    def get_order(self, tenant_id, order_id):
        order = parse.quote(str(order_id), safe="")
        return self._request("GET", f"{self._tenant_path(tenant_id)}/orders/{order}")

    def cancel_order(self, tenant_id, order_id, *, idempotency_key):
        order = parse.quote(str(order_id), safe="")
        return self._request(
            "POST",
            f"{self._tenant_path(tenant_id)}/orders/{order}/cancel",
            {},
            extra_headers={"X-Idempotency-Key": idempotency_key},
        )

    def refund_order(self, tenant_id, order_id, *, amount, idempotency_key):
        order = parse.quote(str(order_id), safe="")
        return self._request(
            "POST",
            f"{self._tenant_path(tenant_id)}/orders/{order}/refund",
            {},
            extra_headers={"X-Idempotency-Key": idempotency_key},
        )
