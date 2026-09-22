from unittest.mock import patch

from django.test import TestCase

from scripts.validate_preprod_env import validate_preprod_environment


class RuntimeHealthTests(TestCase):
    def test_liveness_does_not_depend_on_database(self):
        with patch('config.urls.connection.cursor', side_effect=RuntimeError('database unavailable')):
            response = self.client.get('/healthz/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_readiness_checks_database(self):
        response = self.client.get('/readyz/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ready'})

    def test_readiness_fails_closed_when_database_is_unavailable(self):
        with patch('config.urls.connection.cursor', side_effect=RuntimeError('database unavailable')):
            response = self.client.get('/readyz/')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'unavailable'})


class PreprodEnvironmentValidationTests(TestCase):
    def valid_values(self):
        return {
            'DJANGO_SECRET_KEY': 'd' * 60,
            'POSTAS_PLATFORM_SERVICE_TOKEN': 's' * 40,
            'AI_EXTRACTOR_TOKEN': 'a' * 40,
            'POSTAS_DB_PASSWORD': 'postas-password-123',
            'PLATFORM_DB_PASSWORD': 'platform-password-123',
            'POSTAS_DATABASE_URL': 'postgresql://user:postas-password-123@postas_db:5432/db',
            'PLATFORM_DATABASE_URL': 'postgresql+psycopg://user:platform-password-123@platform_db:5432/db',
            'MERCADO_PAGO_REDIRECT_URI': 'https://localhost:8443/api/v1/mercado-pago/oauth/callback',
        }

    def test_valid_environment_passes(self):
        validate_preprod_environment(self.valid_values())

    def test_placeholders_and_short_secrets_are_rejected_without_values_in_error(self):
        values = self.valid_values()
        values['DJANGO_SECRET_KEY'] = 'CHANGE_ME'

        with self.assertRaisesRegex(ValueError, 'DJANGO_SECRET_KEY') as raised:
            validate_preprod_environment(values)

        self.assertNotIn('CHANGE_ME', str(raised.exception))

    def test_database_host_and_password_must_match_compose_contract(self):
        values = self.valid_values()
        values['PLATFORM_DATABASE_URL'] = (
            'postgresql+psycopg://user:wrong-password@postas_db:5432/db'
        )

        with self.assertRaisesRegex(ValueError, 'PLATFORM_DATABASE_URL'):
            validate_preprod_environment(values)
