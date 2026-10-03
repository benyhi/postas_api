"""Offline tests for catalogue, orchestration and image storage boundaries."""
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_catalog
import demo_images
import seed_demo


class CatalogueTests(unittest.TestCase):
    def test_reviewed_catalogue_matches_csv_and_has_distinct_spanish_names(self):
        rows = demo_catalog.load_catalog(seed_demo.ROOT / 'openfoodfacts_products_clean.csv')
        self.assertEqual(len(rows), 100)
        self.assertEqual(len({row['name'] for row in rows}), 100)
        self.assertEqual(len({row['barcode'] for row in rows}), 100)
        by_code = {row['barcode']: row for row in rows}
        self.assertIn('Protein', by_code['7790742358608']['name'])
        self.assertEqual(by_code['7790742358608']['category'], 'Leches y bebidas vegetales')
        self.assertIn('Mediatarde clásicas', by_code['7790040143586']['name'])
        self.assertIn('Oreo', by_code['7622201735258']['name'])
        self.assertGreaterEqual(len({r['category'] for r in rows[:10]}), 8)

    def test_manifest_repeatability_and_leap_year(self):
        args = (seed_demo.ROOT / 'openfoodfacts_products_clean.csv', 42, '2024-02-29T12:00:00+00:00', [1, 3])
        first = seed_demo.make_manifest(*args)
        self.assertEqual(first, seed_demo.make_manifest(*args))
        self.assertTrue(first['start_at'].startswith('2023-02-28'))
        self.assertEqual([t['plan_code'] for t in first['tenants']], ['business_ai', 'free'])

    def test_database_environments_are_separate(self):
        with patch.dict(os.environ, {'DATABASE_URL': 'must-not-leak', 'POSTAS_DEMO_DATABASE_URL': 'postas'}, clear=True):
            with patch.object(seed_demo, 'dotenv_values', return_value={'DATABASE_URL': 'platform'}):
                self.assertEqual(seed_demo.environment(Path('.'), 'PLATFORM')['DATABASE_URL'], 'platform')
                self.assertEqual(seed_demo.environment(Path('.'), 'POSTAS')['DATABASE_URL'], 'postas')


class ImageTests(unittest.TestCase):
    ENV = {'R2_BUCKET_NAME': 'bucket', 'R2_PUBLIC_URL': 'https://cdn.example.test'}
    PRODUCT = {'barcode': '123', 'source_image_url': 'https://images.openfoodfacts.org/front.jpg'}

    def test_rejects_untrusted_source_without_network(self):
        with patch.object(demo_images.requests, 'get') as get:
            with self.assertRaises(ValueError):
                demo_images.fetch_image('http://127.0.0.1/private', demo_images.SOURCE_HOSTS)
            get.assert_not_called()

    def test_dry_run_never_uploads(self):
        client = Mock()
        client.head_object.side_effect = demo_images.ClientError({'Error': {'Code': '404'}}, 'HeadObject')
        with patch.object(demo_images, 'r2_config', return_value=client), patch.object(demo_images, 'fetch_image', return_value=(b'photo', 'image/jpeg')):
            result = demo_images.copy_images([self.PRODUCT], self.ENV, dry_run=True)
        client.put_object.assert_not_called()
        self.assertTrue(result[0]['image_url'].startswith('https://cdn.example.test/demo/'))

    def test_existing_image_verified_and_never_overwritten(self):
        client = Mock()
        client.head_object.return_value = {'Metadata': {'source': 'production-demo-v1', 'sha256': demo_images.hashlib.sha256(b'photo').hexdigest()}}
        with patch.object(demo_images, 'r2_config', return_value=client), patch.object(demo_images, 'fetch_image', return_value=(b'photo', 'image/jpeg')):
            demo_images.copy_images([self.PRODUCT], self.ENV)
        client.put_object.assert_not_called()

    def test_unowned_r2_object_rejected(self):
        client = Mock()
        client.head_object.return_value = {'Metadata': {}}
        with patch.object(demo_images, 'r2_config', return_value=client):
            with self.assertRaisesRegex(ValueError, 'ajeno'):
                demo_images.copy_images([self.PRODUCT], self.ENV)
        client.put_object.assert_not_called()

    def test_html_response_claiming_image_type_is_rejected(self):
        response = Mock(is_redirect=False)
        response.headers = {'Content-Type': 'image/jpeg'}
        response.iter_content.return_value = [b'<html>Access denied</html>']
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(demo_images.requests, 'get', return_value=response):
            with self.assertRaisesRegex(ValueError, 'no es una imagen'):
                demo_images.fetch_image(self.PRODUCT['source_image_url'], demo_images.SOURCE_HOSTS)

    def test_source_redirect_cannot_escape_allowed_hosts(self):
        response = Mock(is_redirect=True)
        response.headers = {'Location': 'https://private.example.test/image.jpg'}
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(demo_images.requests, 'get', return_value=response) as get:
            with self.assertRaisesRegex(ValueError, 'Origen'):
                demo_images.fetch_image(self.PRODUCT['source_image_url'], demo_images.SOURCE_HOSTS)
        self.assertEqual(get.call_count, 1)

    def test_public_image_mismatch_stops_without_overwriting_existing_object(self):
        client = Mock()
        client.head_object.return_value = {'Metadata': {'source': 'production-demo-v1',
            'sha256': demo_images.hashlib.sha256(b'expected photo').hexdigest()}}
        with patch.object(demo_images, 'r2_config', return_value=client), patch.object(
                demo_images, 'fetch_image', return_value=(b'wrong public photo', 'image/jpeg')):
            with self.assertRaisesRegex(ValueError, 'diferente'):
                demo_images.copy_images([self.PRODUCT], self.ENV)
        client.put_object.assert_not_called()


class LauncherTests(unittest.TestCase):
    def test_dry_run_preflights_both_without_mutation_phases(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'manifest.json'
            with patch.object(seed_demo, 'run_child', return_value={}) as child, patch.object(seed_demo, 'copy_images', side_effect=lambda products, env, **kwargs: products) as images:
                seed_demo.main(['--dry-run', '--manifest', str(target), '--platform-python', sys.executable,
                                '--as-of', '2026-01-02T12:00:00+00:00'])
            self.assertFalse(target.exists())
            self.assertEqual([c.args[0][-1] for c in child.call_args_list], ['preflight', 'preflight'])
            self.assertTrue(images.call_args.kwargs['dry_run'])

    def test_postas_failure_keeps_manifest_for_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'manifest.json'
            with patch.dict(os.environ, {'DEMO_SEED_PASSWORD': 'only-in-test'}), patch.object(seed_demo, 'run_child', side_effect=[{}, {}, {}, RuntimeError('interrupted')]), patch.object(seed_demo, 'copy_images', side_effect=lambda products, env, **kwargs: products):
                with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                    seed_demo.main(['--manifest', str(target), '--platform-python', sys.executable,
                                    '--as-of', '2026-01-02T12:00:00+00:00'])
            data = json.loads(target.read_text(encoding='utf-8'))
            self.assertEqual(data['as_of'], '2026-01-02T12:00:00+00:00')
            self.assertNotIn('completed', data)


if __name__ == '__main__':
    unittest.main()
