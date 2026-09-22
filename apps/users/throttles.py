import hashlib

from rest_framework.throttling import SimpleRateThrottle


def _digest_identity(*parts) -> str:
    normalized = ':'.join(str(part or '').strip().casefold() for part in parts)
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


class _IPRateThrottle(SimpleRateThrottle):
    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }


class LoginIPRateThrottle(_IPRateThrottle):
    scope = 'auth_login_ip'


class LoginIdentityRateThrottle(SimpleRateThrottle):
    scope = 'auth_login_identity'

    def get_cache_key(self, request, view):
        tenant_id = request.data.get('tenant_id')
        username = request.data.get('username')
        if not tenant_id or not username:
            return None
        return self.cache_format % {
            'scope': self.scope,
            'ident': _digest_identity(tenant_id, username),
        }


class PasswordResetIPRateThrottle(_IPRateThrottle):
    scope = 'password_reset_ip'


class PasswordResetIdentityRateThrottle(SimpleRateThrottle):
    scope = 'password_reset_identity'

    def get_cache_key(self, request, view):
        tenant_id = request.data.get('tenant_id')
        email = request.data.get('email')
        if not tenant_id or not email:
            return None
        return self.cache_format % {
            'scope': self.scope,
            'ident': _digest_identity(tenant_id, email),
        }


class PasswordResetConfirmRateThrottle(_IPRateThrottle):
    scope = 'password_reset_confirm'
