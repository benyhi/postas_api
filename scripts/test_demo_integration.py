"""Opt-in offline contract test across both real seed entrypoints.

Run with RUN_DEMO_INTEGRATION=1 using the Postas virtualenv. Both databases,
the manifest and the network guard live exclusively in a temporary directory.
Platform must be adjacent, or selected with DEMO_TEST_PLATFORM_DIR.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seed_demo


@unittest.skipUnless(os.environ.get("RUN_DEMO_INTEGRATION") == "1", "opt-in full annual dataset")
class DemoIntegrationTests(unittest.TestCase):
    def test_migrated_databases_share_annual_usage_and_replay_without_duplicates(self):
        postas = seed_demo.ROOT
        platform = Path(os.environ.get("DEMO_TEST_PLATFORM_DIR", postas.parent / "postas_platform_api"))
        platform_python = Path(os.environ.get("DEMO_TEST_PLATFORM_PYTHON", platform / "env/Scripts/python.exe"))
        self.assertTrue(platform_python.is_file(), "Platform virtualenv is required")
        with tempfile.TemporaryDirectory(prefix="postas-demo-integration-") as directory:
            temporary = Path(directory)
            # The normal settings loaders use setdefault, so these explicit DB URLs
            # cannot be replaced by either repository's .env file.
            guard = temporary / "sitecustomize.py"
            guard.write_text(
                "import socket\n"
                "def forbidden(*args, **kwargs):\n"
                "    raise AssertionError('Network forbidden in demo integration test')\n"
                "socket.socket.connect = forbidden\n"
                "socket.socket.connect_ex = forbidden\n"
                "socket.create_connection = forbidden\n", encoding="utf-8")
            postas_db, platform_db = temporary / "postas.sqlite3", temporary / "platform.sqlite3"

            def environment(repo, database):
                return {**os.environ, "DATABASE_URL": f"sqlite:///{database.as_posix()}",
                        "PYTHONPATH": os.pathsep.join((str(temporary), str(repo))),
                        "PYTHONIOENCODING": "utf-8", "SECRET_KEY": "isolated-test-secret",
                        "DEBUG": "False", "CACHE_URL": "", "DEMO_SEED_PASSWORD": "isolated-demo-password",
                        "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
                        "ARCA_PRODUCTION_CALLS_ENABLED": "False"}

            def run(repo, python, args, database, *, report=False):
                completed = subprocess.run([str(python), *map(str, args)], cwd=repo,
                    env=environment(repo, database), capture_output=True, text=True, encoding="utf-8", timeout=300)
                self.assertEqual(completed.returncode, 0,
                    f"{repo.name}: {args}\n{completed.stdout[-3000:]}\n{completed.stderr[-3000:]}")
                if report:
                    return json.loads(completed.stdout.strip().splitlines()[-1])

            run(postas, sys.executable, [postas / "manage.py", "migrate", "--noinput"], postas_db)
            run(platform, platform_python, ["-m", "alembic", "upgrade", "head"], platform_db)
            manifest = seed_demo.make_manifest(postas / "openfoodfacts_products_clean.csv", 20261002,
                                               "2026-01-02T12:00:00+00:00", list(range(1, 9)))
            for product in manifest["products"]:
                product["image_url"] = f"https://demo-images.example.invalid/{product['barcode']}.jpg"
            manifest_path = temporary / "manifest.json"

            def save_manifest():
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            def seed_postas(phase):
                return run(postas, sys.executable, [postas / "manage.py", "seed_demo", "--manifest",
                           manifest_path, "--phase", phase], postas_db, report=True)

            def seed_platform(phase):
                return run(platform, platform_python, [platform / "scripts/seed_demo.py", "--manifest",
                           manifest_path, "--phase", phase], platform_db, report=True)

            def snapshot(database):
                with closing(sqlite3.connect(database)) as db:
                    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                    return {table: db.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0]
                            for table in tables}

            save_manifest()
            before = snapshot(postas_db), snapshot(platform_db)
            seed_platform("preflight")
            seed_postas("preflight")
            self.assertEqual(before, (snapshot(postas_db), snapshot(platform_db)))
            self.assertEqual(seed_platform("subscriptions")["created"], 8)
            result = seed_postas("load")
            self.assertEqual(len(result["counts"]), 8)
            expected_products = [100, 100, 20, 100, 100, 10, 10, 10]
            for index, tenant in enumerate(manifest["tenants"]):
                count = result["counts"][tenant["id"]]
                self.assertEqual(count["products"], expected_products[index])
                self.assertEqual(count["users"], 3)
                self.assertEqual(count["registers"], 2)
                if tenant["plan_code"] in {"business", "business_ai", "custom"}:
                    self.assertEqual(count["sales"], 10000)
            manifest["usage_events"] = result["usage_events"]
            save_manifest()
            events = len(manifest["usage_events"])
            self.assertEqual(seed_platform("usage")["created"], events)
            self.assertEqual(seed_platform("verify")["events"], events)
            self.assertEqual(seed_postas("verify"), result)
            sales = sum(item["sales"] for item in result["counts"].values())
            with closing(sqlite3.connect(platform_db)) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM billing_plans").fetchone()[0], 8)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM billing_features").fetchone()[0], 14)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM billing_tenant_subscriptions").fetchone()[0], 8)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM billing_payments").fetchone()[0], 4 * 13)
                self.assertEqual(db.execute("SELECT SUM(amount) FROM billing_usage_events WHERE feature_key='pos_sales'").fetchone()[0], sales)
                self.assertEqual(db.execute("SELECT SUM(used) FROM billing_usage_counters WHERE feature_key='pos_sales'").fetchone()[0], sales)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM billing_payments WHERE amount<=0 OR provider!='manual' OR provider_status!='approved'").fetchone()[0], 0)
            loaded = snapshot(postas_db), snapshot(platform_db)
            self.assertEqual(seed_platform("subscriptions")["created"], 0)
            self.assertEqual(seed_postas("load"), result)
            self.assertEqual(seed_platform("usage")["created"], 0)
            seed_platform("verify")
            self.assertEqual(loaded, (snapshot(postas_db), snapshot(platform_db)))
            print(f"Verified {sales} sales, {events} usage events, 8 tenants and idempotent replay.", flush=True)


if __name__ == "__main__":
    unittest.main()
