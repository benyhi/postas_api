"""Load an explicitly prepared production-demo manifest without remote side effects."""
import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.users.demo_seed import load_tenant, preflight, result, validate_manifest


class Command(BaseCommand):
    help = "Preflight, load or verify the cross-repository production demo dataset."

    def add_arguments(self, parser):
        parser.add_argument("--manifest", required=True)
        parser.add_argument("--phase", choices=("preflight", "load", "verify"), default="preflight")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            manifest = json.loads(Path(options["manifest"]).read_text(encoding="utf-8"))
            preflight(manifest)
            if options["dry_run"] or options["phase"] == "preflight":
                payload = {"phase": "preflight", "tenants": len(manifest["tenants"]), "writes": 0}
            else:
                if options["phase"] == "load":
                    validate_manifest(manifest, images=True)
                    password = os.environ.get("DEMO_SEED_PASSWORD")
                    if not password or len(password) < 12:
                        raise CommandError("Set DEMO_SEED_PASSWORD with at least 12 characters.")
                    for tenant in manifest["tenants"]:
                        load_tenant(manifest, tenant, password)
                payload = result(manifest)
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise CommandError(f"Invalid demo manifest: {exc}") from exc
        self.stdout.write(json.dumps(payload, ensure_ascii=False))
