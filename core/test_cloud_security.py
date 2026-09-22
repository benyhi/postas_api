import uuid
from unittest.mock import Mock, patch

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.users.models import User


class PublicImageSecurityTests(TestCase):
    def setUp(self):
        self.tenant_id = uuid.uuid4()
        self.other_tenant_id = uuid.uuid4()
        self.user = User.objects.create_user(
            tenant_id=self.tenant_id,
            username='image-user',
            email='image@example.com',
            password='StrongPass!123',
            role=User.Role.EMPLOYEE,
        )
        refresh = RefreshToken.for_user(self.user)
        access = refresh.access_token
        access['tenant_id'] = str(self.tenant_id)
        access['role'] = self.user.role
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

    def test_anonymous_request_is_rejected(self):
        response = APIClient().get('/api/v1/cloud/public/images/')
        self.assertEqual(response.status_code, 401)

    @patch('core.cloud.views._get_service')
    def test_list_ignores_query_tenant_and_uses_jwt_tenant(self, get_service):
        service = Mock()
        service.list_objects.return_value = {'images': [], 'count': 0}
        get_service.return_value = (service, None)

        response = self.client.get(
            f'/api/v1/cloud/public/images/?tenant_id={self.other_tenant_id}'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            service.list_objects.call_args.kwargs['prefix'],
            f'{self.tenant_id}/',
        )

    @patch('core.cloud.views._get_service')
    def test_detail_rejects_other_tenant_key(self, get_service):
        service = Mock()
        get_service.return_value = (service, None)

        response = self.client.get(
            f'/api/v1/cloud/public/images/{self.other_tenant_id}/images/invoice.png/'
        )

        self.assertEqual(response.status_code, 403)
        service.get.assert_not_called()
