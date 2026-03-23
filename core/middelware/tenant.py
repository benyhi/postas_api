class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant_id = request.headers.get("X-Tenant-ID")

        if not tenant_id:
            raise Exception("Tenant requerido")

        request.tenant_id = tenant_id
        return self.get_response(request)