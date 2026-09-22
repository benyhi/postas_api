import os
from urllib.parse import unquote, urlparse


MINIMUM_LENGTHS = {
    'DJANGO_SECRET_KEY': 50,
    'POSTAS_PLATFORM_SERVICE_TOKEN': 32,
    'AI_EXTRACTOR_TOKEN': 32,
    'POSTAS_DB_PASSWORD': 16,
    'PLATFORM_DB_PASSWORD': 16,
}


def validate_preprod_environment(values):
    errors = []
    for name, minimum_length in MINIMUM_LENGTHS.items():
        value = values.get(name, '')
        if not value or 'CHANGE_ME' in value or len(value) < minimum_length:
            errors.append(name)

    database_contracts = (
        ('POSTAS_DATABASE_URL', 'POSTAS_DB_PASSWORD', 'postas_db'),
        ('PLATFORM_DATABASE_URL', 'PLATFORM_DB_PASSWORD', 'platform_db'),
    )
    for url_name, password_name, expected_host in database_contracts:
        raw_url = values.get(url_name, '')
        try:
            parsed = urlparse(raw_url)
            password_matches = unquote(parsed.password or '') == values.get(password_name, '')
            if parsed.hostname != expected_host or not password_matches:
                errors.append(url_name)
        except ValueError:
            errors.append(url_name)

    redirect_uri = values.get('MERCADO_PAGO_REDIRECT_URI', '')
    if redirect_uri and urlparse(redirect_uri).scheme != 'https':
        errors.append('MERCADO_PAGO_REDIRECT_URI')

    if errors:
        invalid_names = ', '.join(sorted(set(errors)))
        raise ValueError(f'Invalid preproduction environment variables: {invalid_names}')


def main():
    validate_preprod_environment(os.environ)
    print('Preproduction environment validation passed.')


if __name__ == '__main__':
    main()
