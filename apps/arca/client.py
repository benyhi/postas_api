from urllib import parse

from apps.platform_billing.client import PlatformBillingClient


class PlatformArcaClient(PlatformBillingClient):
    def get_profile(self, tenant_id, environment):
        return self._request(
            "GET",
            f"/internal/v1/arca/tenants/{parse.quote(str(tenant_id), safe='')}/profiles/{environment}",
        )

    def put_profile(self, tenant_id, environment, payload):
        return self._request(
            "PUT",
            f"/internal/v1/arca/tenants/{parse.quote(str(tenant_id), safe='')}/profiles/{environment}",
            payload,
        )

    def delete_profile(self, tenant_id, environment):
        return self._request(
            "DELETE",
            f"/internal/v1/arca/tenants/{parse.quote(str(tenant_id), safe='')}/profiles/{environment}",
        )

    def validate_profile(self, tenant_id, environment):
        return self._request(
            "POST",
            f"/internal/v1/arca/tenants/{parse.quote(str(tenant_id), safe='')}/profiles/{environment}/validate",
            {},
        )

    def discover_sales_points(self, tenant_id, payload):
        return self._request(
            "POST",
            f"/internal/v1/arca/tenants/{parse.quote(str(tenant_id), safe='')}/sales-points",
            payload,
        )

    def create_invoice(self, tenant_id, environment, payload, *, explicit=False, automatic=False):
        suffix = "/explicit" if explicit else "/automatic" if automatic else ""
        return self._request(
            "POST",
            f"/internal/v1/arca/tenants/{parse.quote(str(tenant_id), safe='')}/invoices/{environment}{suffix}",
            payload,
        )

    def get_by_external_id(self, tenant_id, external_id):
        return self._request(
            "GET",
            f"/internal/v1/arca/tenants/{parse.quote(str(tenant_id), safe='')}/invoices/by-external-id/{parse.quote(str(external_id), safe='')}",
        )

    def get_by_sale(self, tenant_id, sale_id):
        return self._request(
            "GET",
            f"/internal/v1/arca/tenants/{parse.quote(str(tenant_id), safe='')}/invoices/by-sale/{parse.quote(str(sale_id), safe='')}",
        )

    def list_invoices(self, tenant_id, *, offset, limit):
        query = parse.urlencode({"offset": offset, "limit": limit})
        return self._request(
            "GET",
            f"/internal/v1/arca/tenants/{parse.quote(str(tenant_id), safe='')}/invoices?{query}",
        )

    def get_fiscal(self, tenant_id, *, environment, point_of_sale, voucher_type, voucher_number):
        query = parse.urlencode(
            {
                "environment": environment,
                "point_of_sale": point_of_sale,
                "voucher_type": voucher_type,
                "voucher_number": voucher_number,
            }
        )
        return self._request(
            "GET",
            f"/internal/v1/arca/tenants/{parse.quote(str(tenant_id), safe='')}/invoices/fiscal?{query}",
        )

    def get_last_voucher(self, tenant_id, environment, voucher_type=None):
        path = f"/internal/v1/arca/tenants/{parse.quote(str(tenant_id), safe='')}/last-voucher/{environment}"
        if voucher_type is not None:
            path = f"{path}?{parse.urlencode({'voucher_type': voucher_type})}"
        return self._request("GET", path)
