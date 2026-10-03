"""Offline checks for the temporary Railway demo seed runner bundle."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_railway_seed_bundle as bundle


class BundleTests(unittest.TestCase):
    def test_bundle_contains_runtime_files_but_no_local_data_or_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            postas = root / 'postas_api'
            platform = root / 'postas_platform_api'
            files = {
                postas: [
                    'apps/products/models.py', 'apps/products/tests/test_models.py',
                    'apps/products/__pycache__/models.pyc', 'config/settings.py',
                    'core/utils/audit.py', 'manage.py', 'requirements.txt',
                    'openfoodfacts_products_clean.csv', 'scripts/demo_catalog.py',
                    'scripts/demo_images.py', 'scripts/seed_demo.py',
                    'scripts/Dockerfile.seed_demo', '.env', 'db.sqlite3',
                ],
                platform: [
                    'app/billing/seed.py', 'app/billing/tests/test_seed.py',
                    'alembic/versions/initial.py', 'alembic.ini',
                    'requirements.txt', 'scripts/seed_demo.py', '.env',
                ],
            }
            for repo, names in files.items():
                for name in names:
                    path = repo / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(name, encoding='utf-8')
            destination = postas / '.demo-seed' / 'bundle'
            with patch.object(bundle, 'POSTAS', postas), patch.object(bundle, 'PLATFORM', platform):
                bundle.build(destination)
            self.assertTrue((destination / 'Dockerfile').is_file())
            self.assertTrue((destination / 'postas_api/apps/products/models.py').is_file())
            self.assertTrue((destination / 'postas_platform_api/app/billing/seed.py').is_file())
            self.assertFalse((destination / 'postas_api/.env').exists())
            self.assertFalse((destination / 'postas_api/db.sqlite3').exists())
            self.assertFalse((destination / 'postas_api/apps/products/tests').exists())
            self.assertFalse((destination / 'postas_platform_api/app/billing/tests').exists())
            with patch.object(bundle, 'POSTAS', postas), patch.object(bundle, 'PLATFORM', platform):
                with self.assertRaises(FileExistsError):
                    bundle.build(destination)
                with self.assertRaisesRegex(ValueError, 'bajo .demo-seed'):
                    bundle.build(root / 'outside')

    def test_copy_file_rejects_symlink_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / 'postas_api'
            repo.mkdir()
            outside = root / 'outside.py'
            outside.write_text('sensitive', encoding='utf-8')
            link = repo / 'apps' / 'linked.py'
            link.parent.mkdir()
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest('Symlinks are not available on this system')
            with self.assertRaisesRegex(ValueError, 'fuera del repo'):
                bundle.copy_file(repo, Path('apps/linked.py'), repo / '.demo-seed/bundle')

    def test_dockerfile_is_explicitly_started_and_contains_both_apis(self):
        dockerfile = (Path(__file__).resolve().parent / 'Dockerfile.seed_demo').read_text(encoding='utf-8')
        self.assertIn('COPY postas_api /app/postas_api', dockerfile)
        self.assertIn('COPY postas_platform_api /app/postas_platform_api', dockerfile)
        self.assertIn('CMD ["sleep", "infinity"]', dockerfile)
        self.assertNotIn('RUN python scripts/seed_demo.py', dockerfile)


if __name__ == '__main__':
    unittest.main()
