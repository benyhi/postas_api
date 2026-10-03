"""Copy the reviewed product photos to a dedicated, resumable R2 namespace."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urljoin

import boto3
import requests
from botocore.config import Config
from botocore.exceptions import ClientError


MAX_BYTES = 5 * 1024 * 1024
SOURCE_HOSTS = {'images.openfoodfacts.org', 'static.openfoodfacts.org'}


def image_mime(data):
    """Recognize supported binary formats without trusting HTTP Content-Type."""
    if data.startswith(b'\xff\xd8\xff') and data.rstrip().endswith(b'\xff\xd9'):
        return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n') and b'IEND' in data[-12:]:
        return 'image/png'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def fetch_image(url, allowed_hosts):
    for _ in range(4):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname not in allowed_hosts or parsed.username:
            raise ValueError('Origen de imagen no permitido.')
        with requests.get(url, timeout=(10, 30), stream=True, allow_redirects=False) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers['Location'])
                continue
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise ValueError('Imagen mayor a 5 MB.')
            mime = image_mime(bytes(data))
            if not mime:
                raise ValueError('El contenido descargado no es una imagen compatible.')
            return bytes(data), mime
    raise ValueError('Demasiadas redirecciones de imagen.')


def r2_config(env):
    required = ('R2_BUCKET_NAME', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY',
                'R2_ENDPOINT_URL', 'R2_PUBLIC_URL')
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise ValueError('Falta configuración R2: ' + ', '.join(missing))
    if urlparse(env['R2_PUBLIC_URL']).scheme != 'https':
        raise ValueError('R2_PUBLIC_URL debe ser una URL pública HTTPS.')
    return boto3.client('s3', endpoint_url=env['R2_ENDPOINT_URL'],
                        aws_access_key_id=env['R2_ACCESS_KEY_ID'],
                        aws_secret_access_key=env['R2_SECRET_ACCESS_KEY'],
                        region_name=env.get('R2_REGION', 'auto'),
                        config=Config(signature_version='s3v4', retries={'max_attempts': 3}))


def copy_images(products, env, *, dry_run=False):
    client = r2_config(env)
    bucket = env['R2_BUCKET_NAME']
    base = env['R2_PUBLIC_URL'].rstrip('/')
    client.head_bucket(Bucket=bucket)

    def copy_one(product):
        source = product['source_image_url']
        source_hash = hashlib.sha256(source.encode()).hexdigest()[:16]
        key = f"demo/production-demo-v1/products/{product['barcode']}-{source_hash}"
        public_url = f'{base}/{key}'
        try:
            head = client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if str(exc.response.get('Error', {}).get('Code')) not in {'404', 'NoSuchKey', 'NotFound'}:
                raise
            head = None
        if head:
            meta = head.get('Metadata', {})
            if meta.get('source') != 'production-demo-v1' or not meta.get('sha256'):
                raise ValueError(f"Objeto R2 ajeno al seed: {product['barcode']}")
            expected_hash = meta['sha256']
        else:
            try:
                content, mime = fetch_image(source, SOURCE_HOSTS)
            except (ValueError, requests.RequestException):
                # Recovery must stay on the same barcode, never use a generic placeholder.
                response = requests.get(
                    f"https://world.openfoodfacts.org/api/v2/product/{product['barcode']}.json",
                    params={'fields': 'image_front_url,image_url'}, timeout=(10, 30))
                response.raise_for_status()
                remote = response.json().get('product', {})
                replacement = remote.get('image_front_url') or remote.get('image_url')
                if not replacement:
                    raise ValueError(f"Sin imagen para {product['barcode']}")
                content, mime = fetch_image(replacement, SOURCE_HOSTS)
            expected_hash = hashlib.sha256(content).hexdigest()
            if not dry_run:
                client.put_object(Bucket=bucket, Key=key, Body=content, ContentType=mime,
                                  IfNoneMatch='*', Metadata={'source': 'production-demo-v1',
                                                          'sha256': expected_hash})
        if head or not dry_run:
            public_content, _ = fetch_image(public_url, {urlparse(base).hostname})
            if hashlib.sha256(public_content).hexdigest() != expected_hash:
                raise ValueError(f"Imagen pública R2 diferente: {product['barcode']}")
        return dict(product, image_url=public_url)

    def copy(product):
        try:
            return copy_one(product)
        except Exception as exc:
            reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            raise ValueError(f"Imagen del producto {product['barcode']}: {reason}") from None

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(copy, products))


if __name__ == '__main__':
    # Read-only catalogue health check, independent of R2 credentials.
    import json
    from pathlib import Path
    from demo_catalog import load_catalog

    def check_source(product):
        try:
            content, _ = fetch_image(product['source_image_url'], SOURCE_HOSTS)
            return {'barcode': product['barcode'], 'ok': True, 'bytes': len(content)}
        except Exception as exc:
            return {'barcode': product['barcode'], 'ok': False, 'error': type(exc).__name__}

    products = load_catalog(Path(__file__).resolve().parents[1] / 'openfoodfacts_products_clean.csv')
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check_source, products))
    failures = [row for row in results if not row['ok']]
    print(json.dumps({'total': len(results), 'valid': len(results) - len(failures), 'failures': failures}))
    raise SystemExit(bool(failures))
