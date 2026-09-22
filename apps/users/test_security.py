import urllib.parse
import uuid
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.users.models import User
from apps.users.throttles import LoginIdentityRateThrottle


class PasswordResetSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant_id = uuid.uuid4()
        self.user = User.objects.create_user(
            tenant_id=self.tenant_id,
            username='reset-user',
            email='reset@example.com',
            password='OldStrongPass!123',
            role=User.Role.EMPLOYEE,
        )
        self.client = APIClient()

    @patch('apps.users.views.send_password_reset_email')
    def test_reset_token_cannot_be_reused(self, send_email):
        response = self.client.post(
            '/api/v1/auth/password-reset/',
            {'email': self.user.email, 'tenant_id': str(self.tenant_id)},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        reset_url = send_email.call_args.args[1]
        token = urllib.parse.parse_qs(urllib.parse.urlsplit(reset_url).query)['token'][0]

        payload = {'token': token, 'new_password': 'NewStrongPass!456'}
        first = self.client.post('/api/v1/auth/password-reset/confirm/', payload, format='json')
        second = self.client.post('/api/v1/auth/password-reset/confirm/', payload, format='json')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)


class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.tenant_id = uuid.uuid4()
        User.objects.create_user(
            tenant_id=self.tenant_id,
            username='limited-user',
            email='limited@example.com',
            password='StrongPass!123',
            role=User.Role.EMPLOYEE,
        )
        self.client = APIClient()

    def test_login_identity_is_throttled(self):
        payload = {
            'tenant_id': str(self.tenant_id),
            'username': 'limited-user',
            'password': 'wrong-password',
        }
        with patch.object(LoginIdentityRateThrottle, 'rate', '1/min', create=True):
            first = self.client.post('/api/v1/auth/login/', payload, format='json')
            second = self.client.post('/api/v1/auth/login/', payload, format='json')

        self.assertEqual(first.status_code, 400)
        self.assertEqual(second.status_code, 429)
