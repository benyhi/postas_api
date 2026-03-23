from django.http import JsonResponse


EXEMPT_PATHS = [
    "/api/v1/auth/",
    "/admin/",
]


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        if any(path.startswith(prefix) for prefix in EXEMPT_PATHS):
            request.tenant_id = None
            return self.get_response(request)

        # Decode JWT from Authorization header directly,
        # because DRF authentication runs after middleware.
        tenant_id = self._extract_tenant_from_header(request)

        if not tenant_id:
            # Let DRF handle 401 if no token; we just set None
            request.tenant_id = None
            return self.get_response(request)

        request.tenant_id = tenant_id
        return self.get_response(request)

    @staticmethod
    def _extract_tenant_from_header(request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return None
        raw_token = auth_header.split(" ", 1)[1]
        try:
            from rest_framework_simplejwt.tokens import AccessToken
            token = AccessToken(raw_token)
            return token.get("tenant_id")
        except Exception:
            return None
