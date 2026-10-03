import copy
import io
import json
import os
import tempfile
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.cashbox.models import Cashbox, CashRegister
from apps.document_extractor.models import DocumentExtraction
from apps.notifications.models import EmailDelivery
from apps.products.models import Product
from apps.sales.models import Sale
from apps.tenants.models import Tenant
from apps.users.demo_seed import check_conflict, load_tenant, result, schedule
from apps.users.models import User


def fixture(plan="starter"):
    return {"version": 1, "dataset_id": "production-demo-v1", "fingerprint": "test-fixture", "seed": 41,
            "start_at": "2025-01-01T00:00:00+00:00", "as_of": "2025-02-01T12:00:00+00:00",
            "tenants": [{"id": "00000000-0000-0000-0000-000000000001", "name": "Demo", "plan_code": plan}],
            "products": [{"barcode": str(1000000 + i), "name": f"Producto español {i}", "description": "Producto simulado",
                          "category": f"Categoria {i % 12}", "price": "100.10", "cost": "70.00", "unit": "U",
                          "stock": "50", "min_stock": "5", "image_url": f"https://images.example.invalid/{i}.jpg"}
                         for i in range(100)]}


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DemoSeedTests(TestCase):
    def test_load_accounting_dates_and_offline_idempotent_replay(self):
        manifest = fixture()
        with patch("requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")), patch(
                "django.core.mail.send_mail", side_effect=AssertionError("Email forbidden")):
            load_tenant(manifest, manifest["tenants"][0], "test-demo-password")
        first = result(manifest)
        self.assertEqual(Product.objects.count(), 100)
        self.assertEqual(CashRegister.objects.count(), 2)
        self.assertEqual(Cashbox.objects.filter(status="OPEN").count(), 2)
        self.assertEqual(set(User.objects.values_list("role", flat=True)), {"OWNER", "ADMIN", "EMPLOYEE"})
        self.assertFalse(User.objects.filter(is_superuser=True).exists())
        self.assertTrue(all(u.check_password("test-demo-password") for u in User.objects.all()))
        self.assertTrue(all(p.stock > 0 and p.current_suppliers.exists() for p in Product.objects.all()))
        for sale in Sale.objects.select_related("cashbox").prefetch_related("details"):
            self.assertEqual(sale.total, sum(d.subtotal for d in sale.details.all()))
            self.assertEqual(sale.total, sum(Decimal(p["amount"]) for p in sale.payments))
            self.assertEqual(sale.user_id, sale.cashbox.opened_by_id)
            self.assertGreaterEqual(sale.created_at, sale.cashbox.opened_at)
            self.assertLessEqual(sale.created_at, datetime.fromisoformat(manifest["as_of"]))
            if sale.cashbox.closed_at:
                self.assertLess(sale.created_at, sale.cashbox.closed_at)
        for box in Cashbox.objects.filter(status="CLOSED"):
            cash = sum(Decimal(payment["amount"]) for sale in box.sales.filter(status="COMPLETED")
                       for payment in sale.payments if payment["method"] == "CASH")
            self.assertEqual(box.expected_amount, box.initial_amount + cash)
            self.assertEqual(box.final_amount - box.expected_amount, box.difference)
        product = Product.objects.first()
        Product.objects.filter(pk=product.pk).update(stock=7)
        audit_count = AuditLog.objects.count()
        load_tenant(manifest, manifest["tenants"][0], "different-password")
        self.assertEqual(first, result(manifest))
        self.assertEqual(audit_count, AuditLog.objects.count())
        product.refresh_from_db()
        self.assertEqual(product.stock, 7)
        self.assertTrue(User.objects.first().check_password("test-demo-password"))
        self.assertEqual(sum(e["feature_key"] == "pos_sales" for e in first["usage_events"]), Sale.objects.count())

    def test_unowned_tenant_and_orphan_rejected_including_inactive(self):
        manifest = fixture()
        tenant = manifest["tenants"][0]
        Tenant.objects.create(uuid=tenant["id"], name="User data")
        with self.assertRaises(CommandError):
            load_tenant(manifest, tenant, "password")
        Tenant.objects.all().delete()
        User.objects.create(username="orphan", tenant_id=tenant["id"], active=False)
        with self.assertRaises(CommandError):
            check_conflict(manifest, tenant)

    def test_fingerprint_mismatch_and_partial_seed_fail(self):
        manifest = fixture("free")
        load_tenant(manifest, manifest["tenants"][0], "test-demo-password")
        altered = copy.deepcopy(manifest)
        altered["fingerprint"] = "changed"
        with self.assertRaises(CommandError):
            load_tenant(altered, altered["tenants"][0], "test-demo-password")
        Sale.objects.first().delete()
        with self.assertRaises(CommandError):
            result(manifest)

    def test_atomic_rollback_on_error(self):
        manifest = fixture()
        with patch("apps.users.demo_seed.SaleDetail.objects.bulk_create", side_effect=ValueError("failure")):
            with self.assertRaises(ValueError):
                load_tenant(manifest, manifest["tenants"][0], "test-demo-password")
        self.assertEqual(Tenant.objects.count(), 0)
        self.assertEqual(User.objects.count(), 0)

    def test_free_limits_and_two_tenant_isolation(self):
        manifest = fixture("free")
        other = {"id": "00000000-0000-0000-0000-000000000002", "name": "Otro", "plan_code": "test"}
        manifest["tenants"].append(other)
        for tenant in manifest["tenants"]:
            load_tenant(manifest, tenant, "test-demo-password")
            self.assertEqual(Cashbox.objects.filter(tenant_id=tenant["id"], status="OPEN").count(), 1)
        self.assertEqual(Product.objects.filter(tenant_id=other["id"]).count(), 10)
        self.assertEqual(Product.objects.exclude(tenant_id=other["id"]).count(), 20)
        for sale in Sale.objects.select_related("user", "cashbox"):
            self.assertEqual(sale.tenant_id, sale.user.tenant_id)
            self.assertEqual(sale.tenant_id, sale.cashbox.tenant_id)
            self.assertTrue(all(d.product.tenant_id == sale.tenant_id for d in sale.details.select_related("product")))

    def test_year_schedule_exact_volume_and_monthly_custom_limit(self):
        manifest = fixture("custom")
        manifest["as_of"] = "2026-01-01T00:00:00+00:00"
        dates = schedule(manifest, manifest["tenants"][0])
        self.assertEqual(len(dates), 10000)
        self.assertLessEqual(max(Counter(d.strftime("%Y-%m") for d in dates).values()), 1000)
        self.assertEqual(dates, schedule(manifest, manifest["tenants"][0]))

    def test_command_dry_run_needs_no_password_and_writes_nothing(self):
        manifest = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            output = io.StringIO()
            with patch.dict(os.environ, {}, clear=True):
                call_command("seed_demo", manifest=str(path), phase="load", dry_run=True, stdout=output)
        self.assertEqual(json.loads(output.getvalue())["writes"], 0)
        self.assertEqual(Tenant.objects.count(), 0)

    def test_verifier_detects_accounting_corruption(self):
        manifest = fixture("free")
        load_tenant(manifest, manifest["tenants"][0], "test-demo-password")
        sale = Sale.objects.first()
        Sale.objects.filter(pk=sale.pk).update(total=sale.total + 1)
        with self.assertRaisesMessage(CommandError, "Invalid sale detail total"):
            result(manifest)

    def test_simulated_ai_and_email_history_consumption_without_providers(self):
        manifest = fixture("business_ai")
        dates = [datetime.fromisoformat("2025-01-15T15:00:00+00:00")]
        # Exercise the supplemental records without duplicating the 10k-volume schedule test.
        with patch("apps.users.demo_seed.schedule", return_value=dates), patch(
                "requests.sessions.Session.request", side_effect=AssertionError("Network forbidden")):
            load_tenant(manifest, manifest["tenants"][0], "test-demo-password")
        events = result(manifest)["usage_events"]
        self.assertEqual(DocumentExtraction.objects.filter(status="confirmed").count(), 2)
        self.assertEqual(DocumentExtraction.objects.filter(status="failed").count(), 2)
        self.assertEqual(sum(e["feature_key"] == "document_extraction" for e in events), 2)
        self.assertEqual(sum(e["feature_key"] == "cashbox_email_report" for e in events), 4)
        self.assertEqual(EmailDelivery.objects.filter(status="FAILED").count(), 2)
        extraction = DocumentExtraction.objects.filter(status="confirmed").first()
        self.assertEqual(extraction.provider, "simulated")
        self.assertTrue(extraction.extracted_data["is_invoice"])
