"""
Seed the database with realistic test data using OpenFoodFacts products.

Creates: categories, products, cashboxes, sales with details, and audit logs.
Requires test users to exist first (run create_test_users).

Usage:
    python manage.py seed_data
    python manage.py seed_data --sales 200
    python manage.py seed_data --tenant-id <uuid>
    python manage.py seed_data --products-csv openfoodfacts_products_clean.csv
"""
import uuid
import random
import csv
from collections import Counter
from decimal import Decimal
from decimal import InvalidOperation
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db import transaction

from apps.users.models import User
from apps.products.models import Category, Product
from apps.cashbox.models import Cashbox
from apps.sales.models import Sale, SaleDetail
from apps.audit.models import AuditLog


TEST_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
BASE_DIR = Path(__file__).resolve().parents[4]
DEFAULT_PRODUCTS_CSV = BASE_DIR / "openfoodfacts_products_clean.csv"
DEFAULT_CATEGORY_NAME = "Sin categoria"
REQUIRED_PRODUCT_COLUMNS = {
    "name",
    "description",
    "price",
    "cost",
    "unit",
    "stock",
    "min_stock",
    "barcode",
    "image_url",
    "category",
}


def clean_text(value, max_length=None):
    text = (value or "").strip()
    if max_length is not None:
        return text[:max_length]
    return text


def parse_decimal(value):
    text = clean_text(value)
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def positive_decimal_or_fallback(value, fallback, places):
    amount = parse_decimal(value)
    if amount <= 0:
        amount = fallback
    return amount.quantize(places)


def default_price(index):
    return Decimal(500 + ((index * 137) % 4500))


def default_stock(index):
    return Decimal(20 + ((index * 7) % 81))


def unique_product_name(name, barcode, index, duplicate_names):
    if name not in duplicate_names:
        return clean_text(name, 200)

    suffix = f" ({barcode})" if barcode else f" ({index})"
    return f"{name[:200 - len(suffix)]}{suffix}"


def load_products_from_csv(csv_path):
    path = Path(csv_path).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        raise CommandError(f"Products CSV not found: {path}")

    with path.open(encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise CommandError(f"Products CSV is empty: {path}")

        missing_columns = REQUIRED_PRODUCT_COLUMNS - set(reader.fieldnames)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise CommandError(f"Products CSV is missing columns: {missing}")

        raw_rows = list(reader)

    duplicate_names = {
        name
        for name, count in Counter(clean_text(row.get("name")) for row in raw_rows).items()
        if name and count > 1
    }

    products = []
    for index, row in enumerate(raw_rows, start=1):
        raw_name = clean_text(row.get("name"))
        if not raw_name:
            continue

        barcode = clean_text(row.get("barcode"), 100)
        name = unique_product_name(raw_name, barcode, index, duplicate_names)
        category_name = clean_text(row.get("category"), 100) or DEFAULT_CATEGORY_NAME
        price = positive_decimal_or_fallback(row.get("price"), default_price(index), Decimal("0.01"))
        cost = positive_decimal_or_fallback(row.get("cost"), price * Decimal("0.65"), Decimal("0.01"))
        stock = positive_decimal_or_fallback(row.get("stock"), default_stock(index), Decimal("0.001"))
        min_stock = positive_decimal_or_fallback(row.get("min_stock"), stock * Decimal("0.20"), Decimal("0.001"))
        unit = clean_text(row.get("unit"), 5).upper()
        if unit not in {Product.Unit.KG, Product.Unit.U}:
            unit = Product.Unit.U

        products.append({
            "name": name,
            "description": clean_text(row.get("description")) or f"Producto de OpenFoodFacts: {raw_name}",
            "price": price,
            "cost": cost,
            "unit": unit,
            "stock": stock,
            "min_stock": min_stock,
            "barcode": barcode,
            "image_url": clean_text(row.get("image_url"), 500),
            "category_name": category_name,
        })

    if not products:
        raise CommandError(f"Products CSV has no valid products: {path}")

    return products, path


class Command(BaseCommand):
    help = "Seed database with OpenFoodFacts products, cashboxes, sales, and audit logs"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-id",
            type=str,
            default=str(TEST_TENANT_ID),
            help="Tenant UUID (default: 00000000-...0001)",
        )
        parser.add_argument(
            "--sales",
            type=int,
            default=150,
            help="Number of sales to generate (default: 150)",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Spread sales over this many past days (default: 30)",
        )
        parser.add_argument(
            "--products-csv",
            type=str,
            default=str(DEFAULT_PRODUCTS_CSV),
            help="Path to OpenFoodFacts clean products CSV",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        tenant_id = uuid.UUID(options["tenant_id"])
        num_sales = options["sales"]
        num_days = options["days"]
        product_rows, products_csv_path = load_products_from_csv(options["products_csv"])

        # ── Verify users exist ──────────────────────
        users = list(User.objects.filter(tenant_id=tenant_id))
        if not users:
            raise CommandError(
                f"No users found for tenant {tenant_id}. "
                f"Run 'python manage.py create_test_users' first."
            )

        employees = [u for u in users if u.role in ("EMPLOYEE", "ADMIN", "OWNER")]
        self.stdout.write(f"\n  Tenant: {tenant_id}")
        self.stdout.write(f"  Users found: {len(users)}")
        self.stdout.write(f"  Products CSV: {products_csv_path}")
        self.stdout.write(f"  Generating {num_sales} sales over {num_days} days\n")

        # ── Categories ──────────────────────────────
        self.stdout.write("  Creating categories...")
        cat_map = {}
        category_names = sorted({product["category_name"] for product in product_rows})
        Category.all_objects.filter(tenant_id=tenant_id, active=True).exclude(
            name__in=category_names,
        ).update(active=False)
        for name in category_names:
            cat = Category.all_objects.filter(tenant_id=tenant_id, name=name).first()
            if cat:
                if not cat.active:
                    cat.active = True
                    cat.save(update_fields=["active"])
            else:
                cat = Category.all_objects.create(
                    tenant_id=tenant_id,
                    name=name,
                    active=True,
                )
            cat_map[name] = cat
        self.stdout.write(self.style.SUCCESS(f"    {len(cat_map)} categories OK"))

        # ── Products ────────────────────────────────
        self.stdout.write("  Replacing products...")
        deactivated_products = Product.all_objects.filter(
            tenant_id=tenant_id,
            active=True,
        ).update(active=False)
        products = []
        created_products = 0
        updated_products = 0
        for product_data in product_rows:
            barcode = product_data["barcode"]
            prod = None
            if barcode:
                prod = Product.all_objects.filter(
                    tenant_id=tenant_id,
                    barcode=barcode,
                ).order_by("-updated_at").first()
            if prod is None:
                prod = Product.all_objects.filter(
                    tenant_id=tenant_id,
                    name=product_data["name"],
                ).order_by("-updated_at").first()

            product_defaults = {
                "name": product_data["name"],
                "description": product_data["description"],
                "price": product_data["price"],
                "cost": product_data["cost"],
                "unit": product_data["unit"],
                "stock": product_data["stock"],
                "min_stock": product_data["min_stock"],
                "barcode": barcode,
                "image_url": product_data["image_url"],
                "category": cat_map[product_data["category_name"]],
                "active": True,
            }
            if prod:
                for field, value in product_defaults.items():
                    setattr(prod, field, value)
                prod.save(update_fields=list(product_defaults.keys()))
                updated_products += 1
            else:
                prod = Product.all_objects.create(
                    tenant_id=tenant_id,
                    **product_defaults,
                )
                created_products += 1
            products.append(prod)
        self.stdout.write(self.style.SUCCESS(
            f"    {len(products)} products OK "
            f"({created_products} created, {updated_products} updated, "
            f"{deactivated_products} deactivated first)"
        ))

        # ── Cashboxes + Sales ───────────────────────
        self.stdout.write("  Creating cashboxes and sales...")
        now = timezone.now()
        sales_created = 0
        details_created = 0
        cashboxes_created = 0

        # Group sales by day — each day gets one cashbox
        sales_per_day = max(1, num_sales // num_days)

        for day_offset in range(num_days, 0, -1):
            day_start = (now - timedelta(days=day_offset)).replace(
                hour=8, minute=0, second=0, microsecond=0,
            )

            opener = random.choice(employees)
            initial = Decimal(random.randint(5000, 20000))

            cashbox = Cashbox.objects.create(
                tenant_id=tenant_id,
                opened_by=opener,
                initial_amount=initial,
                status=Cashbox.Status.CLOSED,
            )
            # Override auto_now_add
            Cashbox.objects.filter(pk=cashbox.pk).update(opened_at=day_start)
            cashbox.refresh_from_db()
            cashboxes_created += 1

            day_total_cash = Decimal("0")

            day_sales_count = sales_per_day + random.randint(-2, 3)
            day_sales_count = max(1, day_sales_count)

            for sale_idx in range(day_sales_count):
                sale_time = day_start + timedelta(
                    minutes=random.randint(0, 720),  # 8am - 8pm range
                    seconds=random.randint(0, 59),
                )

                seller = random.choice(employees)
                payment = random.choice(["CASH", "CASH", "CASH", "CARD", "TRANSFER"])
                num_items = random.randint(1, 8)
                sale_products = random.sample(products, min(num_items, len(products)))

                total = Decimal("0")
                details = []
                for prod in sale_products:
                    if prod.unit == "KG":
                        qty = Decimal(str(round(random.uniform(0.25, 3.0), 3)))
                    else:
                        qty = Decimal(str(random.randint(1, 5)))

                    subtotal = prod.price * qty
                    total += subtotal
                    details.append(SaleDetail(
                        product=prod,
                        quantity=qty,
                        price=prod.price,
                        subtotal=subtotal,
                    ))

                # Occasional cancelled sale (~5%)
                is_cancelled = random.random() < 0.05
                sale_status = Sale.Status.CANCELLED if is_cancelled else Sale.Status.COMPLETED

                sale = Sale.objects.create(
                    tenant_id=tenant_id,
                    user=seller,
                    cashbox=cashbox,
                    total=total,
                    payment_method=payment,
                    status=sale_status,
                )
                # Override auto_now_add
                Sale.objects.filter(pk=sale.pk).update(created_at=sale_time)

                for d in details:
                    d.sale = sale
                SaleDetail.objects.bulk_create(details)

                if not is_cancelled and payment == "CASH":
                    day_total_cash += total

                sales_created += 1
                details_created += len(details)

            # Close cashbox
            close_time = day_start + timedelta(hours=12, minutes=random.randint(0, 60))
            expected = initial + day_total_cash
            # Simulate small differences
            diff_amount = Decimal(str(random.randint(-500, 500)))
            final = expected + diff_amount

            Cashbox.objects.filter(pk=cashbox.pk).update(
                closed_by=opener,
                closed_at=close_time,
                expected_amount=expected,
                final_amount=final,
                difference=diff_amount,
                status=Cashbox.Status.CLOSED,
            )

        # ── Today's OPEN cashbox ────────────────────
        today_opener = random.choice(employees)
        today_initial = Decimal(random.randint(10000, 20000))
        today_cashbox = Cashbox.objects.create(
            tenant_id=tenant_id,
            opened_by=today_opener,
            initial_amount=today_initial,
            status=Cashbox.Status.OPEN,
        )
        cashboxes_created += 1

        # A few sales today
        today_sales = random.randint(3, 8)
        for _ in range(today_sales):
            seller = random.choice(employees)
            payment = random.choice(["CASH", "CASH", "CARD", "TRANSFER"])
            num_items = random.randint(1, 5)
            sale_products = random.sample(products, min(num_items, len(products)))

            total = Decimal("0")
            details = []
            for prod in sale_products:
                qty = Decimal(str(random.randint(1, 3))) if prod.unit == "U" else Decimal(str(round(random.uniform(0.5, 2.0), 3)))
                subtotal = prod.price * qty
                total += subtotal
                details.append(SaleDetail(
                    product=prod,
                    quantity=qty,
                    price=prod.price,
                    subtotal=subtotal,
                ))

            sale = Sale.objects.create(
                tenant_id=tenant_id,
                user=seller,
                cashbox=today_cashbox,
                total=total,
                payment_method=payment,
            )
            for d in details:
                d.sale = sale
            SaleDetail.objects.bulk_create(details)
            sales_created += 1
            details_created += len(details)

        # ── Audit logs for key events ───────────────
        self.stdout.write("  Creating audit logs...")
        audit_entries = []
        for user in users:
            audit_entries.append(AuditLog(
                tenant_id=tenant_id, user=user,
                action="LOGIN", entity="USER", entity_id=user.uuid,
                metadata={"ip": "127.0.0.1"},
            ))
        for prod in products[:20]:
            audit_entries.append(AuditLog(
                tenant_id=tenant_id, user=random.choice(users),
                action="CREATE", entity="PRODUCT", entity_id=prod.uuid,
                metadata={"name": prod.name},
            ))
        for cat in cat_map.values():
            audit_entries.append(AuditLog(
                tenant_id=tenant_id, user=random.choice(users),
                action="CREATE", entity="CATEGORY", entity_id=cat.uuid,
                metadata={"name": cat.name},
            ))
        AuditLog.objects.bulk_create(audit_entries)

        # ── Summary ─────────────────────────────────
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(self.style.SUCCESS("  Seed complete!"))
        self.stdout.write(f"    Categories:  {len(cat_map)}")
        self.stdout.write(f"    Products:    {len(products)}")
        self.stdout.write(f"    Cashboxes:   {cashboxes_created}")
        self.stdout.write(f"    Sales:       {sales_created}")
        self.stdout.write(f"    SaleDetails: {details_created}")
        self.stdout.write(f"    AuditLogs:   {len(audit_entries)}")
        self.stdout.write(f"    Open cashbox: {today_cashbox.uuid}")
        self.stdout.write(f"{'='*60}\n")
