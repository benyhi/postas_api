"""
Seed the database with realistic test data for a convenience store / kiosk.

Creates: categories, products, cashboxes, sales with details, and audit logs.
Requires test users to exist first (run create_test_users).

Usage:
    python manage.py seed_data
    python manage.py seed_data --sales 200
    python manage.py seed_data --tenant-id <uuid>
"""
import uuid
import random
from decimal import Decimal
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db import transaction

from apps.users.models import User
from apps.products.models import Category, Product
from apps.cashbox.models import Cashbox
from apps.sales.models import Sale, SaleDetail
from apps.audit.models import AuditLog


TEST_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

CATEGORIES_DATA = [
    "Bebidas",
    "Snacks",
    "Lácteos",
    "Panadería",
    "Limpieza",
    "Fiambrería",
    "Congelados",
    "Golosinas",
    "Almacén",
    "Tabaco",
    "Higiene Personal",
    "Verdulería",
]

PRODUCTS_DATA = [
    # (name, category, price, cost, unit, stock, min_stock, barcode)
    # ── Bebidas ──
    ("Coca-Cola 500ml", "Bebidas", 1500, 900, "U", 80, 20, "7790895000591"),
    ("Coca-Cola 1.5L", "Bebidas", 2800, 1800, "U", 50, 15, "7790895001291"),
    ("Coca-Cola 2.25L", "Bebidas", 3500, 2200, "U", 40, 10, "7790895002251"),
    ("Sprite 500ml", "Bebidas", 1500, 900, "U", 60, 15, "7790895050596"),
    ("Fanta 500ml", "Bebidas", 1500, 900, "U", 45, 15, "7790895060595"),
    ("Agua Mineral 500ml", "Bebidas", 800, 400, "U", 100, 30, "7790895100590"),
    ("Agua Mineral 1.5L", "Bebidas", 1200, 650, "U", 60, 20, "7790895100615"),
    ("Agua Saborizada Levité 500ml", "Bebidas", 1100, 600, "U", 50, 15, "7790895200108"),
    ("Cerveza Quilmes 473ml", "Bebidas", 1800, 1100, "U", 120, 30, "7792798002473"),
    ("Cerveza Brahma 473ml", "Bebidas", 1600, 950, "U", 80, 25, "7891149102473"),
    ("Cerveza Corona 355ml", "Bebidas", 2800, 1900, "U", 48, 12, "7501064191355"),
    ("Cerveza Patagonia Amber 473ml", "Bebidas", 3200, 2200, "U", 36, 12, "7792798010473"),
    ("Gatorade 500ml", "Bebidas", 2000, 1200, "U", 40, 10, "7891149440500"),
    ("Speed Max 250ml", "Bebidas", 2200, 1400, "U", 36, 10, "7798068430250"),
    ("Jugo Cepita 1L", "Bebidas", 2500, 1500, "U", 30, 10, "7790580051000"),
    ("Vino Tinto Estancia 750ml", "Bebidas", 4500, 2800, "U", 24, 6, "7790150000750"),
    ("Fernet Branca 750ml", "Bebidas", 12000, 8500, "U", 20, 5, "8000570000750"),
    ("Coca-Cola Zero 500ml", "Bebidas", 1500, 900, "U", 50, 15, "7790895000608"),
    # ── Snacks ──
    ("Papas Lays Clásicas 150g", "Snacks", 2800, 1700, "U", 40, 10, "7790310981504"),
    ("Papas Lays Cheddar 150g", "Snacks", 2800, 1700, "U", 35, 10, "7790310981511"),
    ("Doritos 150g", "Snacks", 3000, 1800, "U", 30, 10, "7790310150027"),
    ("Cheetos 120g", "Snacks", 2500, 1500, "U", 25, 8, "7790310120020"),
    ("Mani Salado 200g", "Snacks", 2200, 1200, "U", 30, 10, "7790310200020"),
    ("Palitos Salados 200g", "Snacks", 1800, 1000, "U", 35, 10, "7790310200037"),
    ("Papas Dia 150g", "Snacks", 1800, 1000, "U", 40, 10, "7790310150034"),
    # ── Lácteos ──
    ("Leche Entera La Serenísima 1L", "Lácteos", 1500, 950, "U", 60, 20, "7790742000010"),
    ("Leche Descremada La Serenísima 1L", "Lácteos", 1600, 1000, "U", 40, 15, "7790742000027"),
    ("Yogur Activia Natural 190g", "Lácteos", 1200, 700, "U", 30, 10, "7791337001900"),
    ("Yogur Ser Frutilla 190g", "Lácteos", 1300, 750, "U", 25, 8, "7791337001917"),
    ("Queso Cremoso 1kg", "Lácteos", 8500, 5500, "KG", 15, 5, "7790742100017"),
    ("Manteca La Serenísima 200g", "Lácteos", 2800, 1800, "U", 20, 8, "7790742200025"),
    ("Dulce de Leche La Serenísima 400g", "Lácteos", 3500, 2200, "U", 25, 8, "7790742400048"),
    ("Crema de Leche 200ml", "Lácteos", 1800, 1100, "U", 20, 8, "7790742500042"),
    # ── Panadería ──
    ("Pan Lactal Bimbo 500g", "Panadería", 2800, 1700, "U", 25, 8, "7790040005000"),
    ("Pan Lactal Integral 500g", "Panadería", 3200, 2000, "U", 20, 8, "7790040005017"),
    ("Medialunas x 6", "Panadería", 2500, 1500, "U", 30, 10, ""),
    ("Facturas Surtidas x 12", "Panadería", 5000, 3200, "U", 15, 5, ""),
    ("Galletitas Criollitas 300g", "Panadería", 1800, 1000, "U", 40, 12, "7622210100030"),
    ("Galletitas Oreo 118g", "Panadería", 1500, 900, "U", 35, 10, "7622210101181"),
    ("Galletitas Pepitos 118g", "Panadería", 1500, 900, "U", 30, 10, "7622210101198"),
    # ── Limpieza ──
    ("Lavandina Ayudín 1L", "Limpieza", 1200, 700, "U", 30, 10, "7790050010009"),
    ("Detergente Magistral 500ml", "Limpieza", 2500, 1500, "U", 25, 8, "7790050050005"),
    ("Jabón en Polvo Skip 800g", "Limpieza", 4500, 2800, "U", 20, 8, "7790050080003"),
    ("Papel Higiénico Elegante x4", "Limpieza", 3200, 2000, "U", 35, 10, "7790060040084"),
    ("Servilletas x 100", "Limpieza", 1500, 800, "U", 40, 10, "7790060100019"),
    ("Bolsas Residuos x 10", "Limpieza", 1800, 1000, "U", 30, 10, "7790060100026"),
    ("Esponja Multiuso", "Limpieza", 800, 400, "U", 50, 15, "7790060100033"),
    # ── Fiambrería ──
    ("Jamón Cocido", "Fiambrería", 12000, 8000, "KG", 8, 3, ""),
    ("Queso Tybo", "Fiambrería", 10000, 6500, "KG", 10, 3, ""),
    ("Salame Milan", "Fiambrería", 14000, 9500, "KG", 6, 2, ""),
    ("Mortadela", "Fiambrería", 8000, 5000, "KG", 8, 3, ""),
    ("Queso Pategras", "Fiambrería", 11000, 7500, "KG", 7, 3, ""),
    # ── Congelados ──
    ("Milanesas de Pollo x 4", "Congelados", 5500, 3500, "U", 20, 8, "7790001550041"),
    ("Empanadas x 12", "Congelados", 7000, 4500, "U", 15, 5, "7790001700121"),
    ("Hamburguesas x 4", "Congelados", 4500, 2800, "U", 25, 8, "7790001450048"),
    ("Papas Fritas Congeladas 1kg", "Congelados", 4000, 2500, "U", 20, 8, "7790001400010"),
    ("Nuggets de Pollo x 12", "Congelados", 5000, 3200, "U", 18, 6, "7790001500121"),
    ("Pizza Congelada", "Congelados", 4500, 2800, "U", 15, 5, "7790001600013"),
    # ── Golosinas ──
    ("Alfajor Havanna", "Golosinas", 2500, 1600, "U", 40, 10, "7790310250010"),
    ("Alfajor Cachafaz", "Golosinas", 1800, 1100, "U", 50, 15, "7790310250027"),
    ("Alfajor Capitán del Espacio", "Golosinas", 1200, 700, "U", 60, 20, "7790310250034"),
    ("Chicle Beldent x 10", "Golosinas", 1500, 900, "U", 40, 10, "7790310350019"),
    ("Caramelos Flynn Paff x 10", "Golosinas", 800, 400, "U", 50, 15, "7790310350026"),
    ("Chocolate Milka 100g", "Golosinas", 3500, 2200, "U", 25, 8, "7622210101006"),
    ("Chocolate Cofler 100g", "Golosinas", 2500, 1500, "U", 30, 10, "7790310450016"),
    ("Turron Arcor", "Golosinas", 1000, 600, "U", 40, 10, "7790310450023"),
    # ── Almacén ──
    ("Arroz Gallo Oro 1kg", "Almacén", 2500, 1500, "U", 40, 12, "7790070010012"),
    ("Fideos Matarazzo 500g", "Almacén", 1800, 1000, "U", 35, 10, "7790070050010"),
    ("Aceite Girasol Cocinero 900ml", "Almacén", 3500, 2200, "U", 25, 8, "7790070090005"),
    ("Azúcar Ledesma 1kg", "Almacén", 1800, 1100, "U", 30, 10, "7790081010009"),
    ("Yerba Mate Playadito 1kg", "Almacén", 5500, 3500, "U", 40, 10, "7790081050005"),
    ("Yerba Mate Taragui 1kg", "Almacén", 4800, 3000, "U", 35, 10, "7790081050012"),
    ("Harina 000 Favorita 1kg", "Almacén", 1500, 800, "U", 30, 10, "7790070110007"),
    ("Atún La Campagnola 170g", "Almacén", 2800, 1800, "U", 25, 8, "7790070170003"),
    ("Sal Fina Celusal 500g", "Almacén", 800, 400, "U", 40, 15, "7790070200006"),
    ("Mermelada BC La Campagnola 390g", "Almacén", 3000, 1800, "U", 20, 8, "7790070300003"),
    ("Café Instantáneo La Virginia 170g", "Almacén", 5000, 3200, "U", 20, 6, "7790070400000"),
    ("Mayonesa Hellmanns 475g", "Almacén", 3200, 2000, "U", 25, 8, "7790400474756"),
    ("Ketchup Hellmanns 400g", "Almacén", 2800, 1700, "U", 20, 8, "7790400400007"),
    ("Mostaza Savora 250g", "Almacén", 2200, 1300, "U", 20, 8, "7790400250005"),
    # ── Tabaco ──
    ("Marlboro Box 20", "Tabaco", 4500, 3600, "U", 50, 15, "77900001"),
    ("Camel 20", "Tabaco", 4200, 3300, "U", 40, 10, "77900002"),
    ("Lucky Strike 20", "Tabaco", 4000, 3100, "U", 35, 10, "77900003"),
    ("Phillip Morris 20", "Tabaco", 3800, 2900, "U", 30, 10, "77900004"),
    ("Jockey 20", "Tabaco", 2500, 1800, "U", 50, 15, "77900005"),
    # ── Higiene Personal ──
    ("Jabón Dove 90g", "Higiene Personal", 1500, 900, "U", 30, 10, "7790500090009"),
    ("Shampoo Head & Shoulders 200ml", "Higiene Personal", 4500, 2800, "U", 15, 5, "7790500200005"),
    ("Desodorante Rexona 150ml", "Higiene Personal", 4000, 2500, "U", 20, 6, "7790500150009"),
    ("Pasta Dental Colgate 90g", "Higiene Personal", 2500, 1500, "U", 25, 8, "7790500100003"),
    ("Alcohol en Gel 250ml", "Higiene Personal", 2000, 1200, "U", 30, 10, "7790500250008"),
    # ── Verdulería ──
    ("Papa", "Verdulería", 1500, 800, "KG", 50, 15, ""),
    ("Cebolla", "Verdulería", 1800, 900, "KG", 30, 10, ""),
    ("Tomate", "Verdulería", 3000, 1800, "KG", 25, 8, ""),
    ("Lechuga", "Verdulería", 2000, 1000, "U", 20, 8, ""),
    ("Zanahoria", "Verdulería", 1500, 800, "KG", 25, 8, ""),
    ("Banana", "Verdulería", 2500, 1500, "KG", 30, 10, ""),
    ("Manzana Roja", "Verdulería", 3000, 1800, "KG", 20, 8, ""),
    ("Naranja", "Verdulería", 2000, 1200, "KG", 25, 8, ""),
]


class Command(BaseCommand):
    help = "Seed database with realistic test data (categories, products, cashboxes, sales, audit logs)"

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

    @transaction.atomic
    def handle(self, *args, **options):
        tenant_id = uuid.UUID(options["tenant_id"])
        num_sales = options["sales"]
        num_days = options["days"]

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
        self.stdout.write(f"  Generating {num_sales} sales over {num_days} days\n")

        # ── Categories ──────────────────────────────
        self.stdout.write("  Creating categories...")
        cat_map = {}
        for name in CATEGORIES_DATA:
            cat, _ = Category.all_objects.get_or_create(
                tenant_id=tenant_id, name=name,
                defaults={"active": True},
            )
            cat_map[name] = cat
        self.stdout.write(self.style.SUCCESS(f"    {len(cat_map)} categories OK"))

        # ── Products ────────────────────────────────
        self.stdout.write("  Creating products...")
        products = []
        for name, cat_name, price, cost, unit, stock, min_stock, barcode in PRODUCTS_DATA:
            prod, _ = Product.all_objects.get_or_create(
                tenant_id=tenant_id, name=name,
                defaults={
                    "description": f"Producto: {name}",
                    "price": Decimal(str(price)),
                    "cost": Decimal(str(cost)),
                    "unit": unit,
                    "stock": Decimal(str(stock)),
                    "min_stock": Decimal(str(min_stock)),
                    "barcode": barcode,
                    "category": cat_map[cat_name],
                    "active": True,
                },
            )
            products.append(prod)
        self.stdout.write(self.style.SUCCESS(f"    {len(products)} products OK"))

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
