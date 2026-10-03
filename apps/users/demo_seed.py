"""Deterministic, offline demo data. Never invokes application integration services."""
import random
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from django.apps import apps
from django.contrib.auth.hashers import make_password
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor

from apps.audit.models import AuditLog
from apps.cashbox.models import Cashbox, CashRegister
from apps.document_extractor.models import DocumentExtraction
from apps.notifications.models import EmailDelivery
from apps.products.models import Category, Product
from apps.sales.models import Sale, SaleDetail
from apps.suppliers.models import ProductSupplier, Supplier
from apps.tenants.models import Tenant, TenantConfig
from apps.users.models import User

NAMESPACE = UUID("2cb75076-e1b9-4b2f-9f5c-b18646cf8b24")
LOCAL = ZoneInfo("America/Argentina/Buenos_Aires")
CENT = Decimal("0.01")
DEMOS = {"test", "demo_2", "demo_3"}
PLANS = DEMOS | {"free", "starter", "business", "business_ai", "custom"}


def identity(tenant_id, kind, key):
    return uuid5(NAMESPACE, f"production-demo-v1:{tenant_id}:{kind}:{key}")


def parse_date(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise CommandError("Manifest timestamps must include a timezone.")
    return result.astimezone(timezone.utc)


def validate_manifest(manifest, *, images=False):
    if manifest.get("version") != 1 or manifest.get("dataset_id") != "production-demo-v1":
        raise CommandError("Unsupported demo manifest.")
    if not manifest.get("fingerprint"):
        raise CommandError("Missing dataset fingerprint.")
    start, end = parse_date(manifest["start_at"]), parse_date(manifest["as_of"])
    if not start < end or end > datetime.now(timezone.utc) + timedelta(minutes=1):
        raise CommandError("Invalid interval or future as_of.")
    tenants = manifest["tenants"]
    if not tenants or len({t["id"] for t in tenants}) != len(tenants):
        raise CommandError("Tenant IDs must be unique.")
    for tenant in tenants:
        UUID(tenant["id"])
        if tenant["plan_code"] not in PLANS:
            raise CommandError("Unknown plan code.")
    products = manifest["products"]
    if len(products) != 100 or len({p["barcode"] for p in products}) != 100:
        raise CommandError("Exactly 100 distinct product barcodes are required.")
    if len({p["name"] for p in products}) != 100:
        raise CommandError("Product names must be unique.")
    for product in products:
        if not product["category"] or not product["name"] or len(product["name"]) > 200:
            raise CommandError("Invalid product name/category.")
        if not 0 < Decimal(str(product["cost"])) < Decimal(str(product["price"])):
            raise CommandError("Product costs must be positive and below prices.")
        if Decimal(str(product["stock"])) <= 0:
            raise CommandError("All products require available stock.")
        if images and not product.get("image_url", "").startswith("https://"):
            raise CommandError("Every product requires an HTTPS image URL.")
    return start, end


def months(start, end):
    cursor = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cursor < end:
        following = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield max(start, cursor), min(end, following), (following - cursor).total_seconds()
        cursor = following


def schedule(manifest, tenant):
    """Allocate quotas by UTC month, then distribute inside local business hours."""
    start, end = parse_date(manifest["start_at"]), parse_date(manifest["as_of"])
    rng = random.Random(f"{manifest['seed']}:{tenant['id']}:dates")
    periods = list(months(start, end))
    plan = tenant["plan_code"]
    quota = 10 if plan in DEMOS else {"free": 20, "starter": 100}.get(plan)
    if quota:
        counts = [int(quota * .8 * (b - a).total_seconds() / duration) for a, b, duration in periods]
    else:
        weights = [(b - a).total_seconds() for a, b, _ in periods]
        counts = [int(10000 * weight / sum(weights)) for weight in weights]
        for index in range(10000 - sum(counts)):
            counts[index % len(counts)] += 1
        if plan == "custom" and max(counts) > 1000:
            raise CommandError("Custom's 10,000 sales need a full-year interval to respect its monthly quota.")
    output = []
    for (a, b, _), count in zip(periods, counts):
        slots = []
        day = a.astimezone(LOCAL).date()
        while day <= b.astimezone(LOCAL).date():
            low = max(a, datetime.combine(day, time(8), LOCAL).astimezone(timezone.utc))
            high = min(b, datetime.combine(day, time(22), LOCAL).astimezone(timezone.utc))
            if low < high:
                slots.append((low, high, 1.4 if day.weekday() >= 5 else 1))
            day += timedelta(days=1)
        if not slots:
            slots = [(a, b, 1)]
        for _ in range(count):
            low, high, _weight = rng.choices(slots, weights=[s[2] for s in slots])[0]
            output.append(low + (high - low) * rng.random())
    return sorted(output)


def marker_for(tenant_id):
    return AuditLog.objects.filter(pk=identity(tenant_id, "marker", "complete")).first()


def check_conflict(manifest, tenant):
    tid = tenant["id"]
    marker = marker_for(tid)
    if marker:
        if (str(marker.tenant_id) != tid or marker.metadata.get("dataset_id") != manifest["dataset_id"]
                or marker.metadata.get("fingerprint") != manifest["fingerprint"]):
            raise CommandError(f"Dataset conflict for tenant {tid}.")
        if not Tenant.objects.filter(pk=tid).exists():
            raise CommandError(f"Incomplete dataset for tenant {tid}.")
        return marker
    if Tenant.objects.filter(pk=tid).exists():
        raise CommandError(f"Existing unrelated tenant {tid}; nothing will be overwritten.")
    # Tenant UUID fields are intentionally not always FKs: include inactive/orphan records.
    for model in apps.get_models():
        field_names = {field.name for field in model._meta.fields}
        if "tenant_id" in field_names or "tenant" in field_names:
            if model._base_manager.filter(tenant_id=tid).exists():
                raise CommandError(f"Unowned records in {model._meta.label} for {tid}.")
    return None


def preflight(manifest):
    validate_manifest(manifest)
    executor = MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        raise CommandError("Apply pending Postas migrations before seeding.")
    for tenant in manifest["tenants"]:
        check_conflict(manifest, tenant)
        schedule(manifest, tenant)


def insert_historical(model, rows, dates):
    if not rows:
        return
    model.objects.bulk_create(rows, batch_size=500)
    fields = list(dates[0])
    for row, values in zip(rows, dates):
        for key, value in values.items():
            setattr(row, key, value)
    model.objects.bulk_update(rows, fields, batch_size=300)


def event(tid, feature, external_id, when, key):
    return {"id": str(identity(tid, "usage", key)), "tenant_id": str(tid),
            "feature_key": feature, "quantity": 1, "occurred_at": when.isoformat(),
            "external_id": str(external_id), "idempotency_key": key}


def load_tenant(manifest, tenant, password):
    tid, plan = tenant["id"], tenant["plan_code"]
    start, end = parse_date(manifest["start_at"]), parse_date(manifest["as_of"])
    with transaction.atomic():
        if check_conflict(manifest, tenant):
            return
        Tenant.objects.create(uuid=tid, name=tenant["name"])
        Tenant.objects.filter(pk=tid).update(created_at=start, updated_at=start)
        TenantConfig.objects.create(tenant_id=tid, notification_email=f"owner.{UUID(tid).int}@example.invalid",
                                    cashbox_email_notifications_enabled=False, automatic_invoicing_enabled=False)
        TenantConfig.objects.filter(tenant_id=tid).update(created_at=start, updated_at=start)
        users = []
        for role in ("OWNER", "ADMIN", "EMPLOYEE"):
            users.append(User(uuid=identity(tid, "user", role), tenant_id=tid, username=role.lower(),
                              email=f"{role.lower()}.{UUID(tid).int}@example.invalid", role=role,
                              password=make_password(password), is_staff=False, is_superuser=False))
        insert_historical(User, users, [{"created_at": start, "updated_at": start}] * 3)
        product_limit = 10 if plan in DEMOS else 20 if plan == "free" else 100
        # Round-robin categories gives a representative selection even in small plans.
        buckets = defaultdict(list)
        for item in manifest["products"]:
            buckets[item["category"]].append(item)
        catalog = []
        while len(catalog) < product_limit:
            for category in sorted(buckets):
                if buckets[category] and len(catalog) < product_limit:
                    catalog.append(buckets[category].pop(0))
        categories = {name: Category(uuid=identity(tid, "category", name), tenant_id=tid, name=name)
                      for name in sorted({item["category"] for item in catalog})}
        insert_historical(Category, list(categories.values()), [{"created_at": start, "updated_at": start}] * len(categories))
        products = [Product(uuid=identity(tid, "product", p["barcode"]), tenant_id=tid,
                            category=categories[p["category"]], **{key: p[key] for key in
                            ("name", "description", "price", "cost", "unit", "stock", "min_stock", "barcode", "image_url")})
                    for p in catalog]
        insert_historical(Product, products, [{"created_at": start, "updated_at": start}] * len(products))
        supplier_count = 2 if plan in DEMOS else {"free": 3, "starter": 5}.get(plan, 10)
        suppliers = [Supplier(uuid=identity(tid, "supplier", i), tenant_id=tid,
                              name=f"Distribuidora Demo {i + 1:02d}", phone=f"+54115550{i:04d}",
                              email=f"proveedor{i + 1}@example.invalid", address=f"Avenida Demo {100 + i}",
                              notes="Proveedor simulado; especialidades asignadas por categoria.") for i in range(supplier_count)]
        insert_historical(Supplier, suppliers, [{"created_at": start, "updated_at": start}] * supplier_count)
        links = [ProductSupplier(uuid=identity(tid, "supplier-product", p.barcode), product=p,
                                 supplier=suppliers[list(categories).index(p.category.name) % supplier_count],
                                 price=p.cost) for p in products]
        insert_historical(ProductSupplier, links, [{"since": start.date()}] * len(links))
        registers = [CashRegister(uuid=identity(tid, "register", i), tenant_id=tid, name=f"Caja {i + 1}") for i in range(2)]
        insert_historical(CashRegister, registers, [{"created_at": start, "updated_at": start}] * 2)
        simultaneous = 1 if plan in DEMOS or plan == "free" else 2
        boxes, box_times, box_map = [], [], {}
        day, last_day = start.astimezone(LOCAL).date(), end.astimezone(LOCAL).date()
        while day <= last_day:
            opening = max(start, datetime.combine(day, time.min, LOCAL).astimezone(timezone.utc))
            closing = datetime.combine(day + timedelta(days=1), time.min, LOCAL).astimezone(timezone.utc)
            for index in range(simultaneous):
                register_index = index if simultaneous == 2 else day.toordinal() % 2
                current = day == last_day
                box = Cashbox(uuid=identity(tid, "cashbox", f"{day}:{index}"), tenant_id=tid,
                              register=registers[register_index], opened_by=users[index + 1],
                              closed_by=None if current else users[index + 1],
                              status="OPEN" if current else "CLOSED", closed_at=None if current else closing,
                              initial_amount=Decimal("15000"))
                boxes.append(box)
                box_times.append({"opened_at": opening})
                box_map[day, index] = box
            day += timedelta(days=1)
        insert_historical(Cashbox, boxes, box_times)
        rng = random.Random(f"{manifest['seed']}:{tid}:sales")
        sales, sale_times, details, audits, audit_times = [], [], [], [], []
        cash = defaultdict(lambda: Decimal(0))
        consumed = defaultdict(lambda: Decimal(0))

        def audit(action, entity, entity_id, when, user, metadata, key):
            audits.append(AuditLog(uuid=identity(tid, "audit", key), tenant_id=tid, user=user,
                                   action=action, entity=entity, entity_id=entity_id,
                                   metadata={"dataset_id": manifest["dataset_id"], "fingerprint": manifest["fingerprint"], **metadata}))
            audit_times.append({"timestamp": when})

        dates = schedule(manifest, tenant)
        cancelled_indices = set(rng.sample(range(len(dates)), round(len(dates) * .03)))
        for index, when in enumerate(dates):
            box = box_map[when.astimezone(LOCAL).date(), index % simultaneous]
            sale_id = identity(tid, "sale", index)
            cancelled = index in cancelled_indices
            total = Decimal(0)
            basket = []
            available = list(products)
            weights = [1 / (i + 1) ** .65 for i in range(len(products))]
            for _ in range(rng.randint(1, min(4, len(products)))):
                selected = rng.choices(range(len(available)), weights=weights)[0]
                basket.append(available.pop(selected))
                weights.pop(selected)
            for item in basket:
                quantity = Decimal(rng.randint(1, 3))
                price = Decimal(str(item.price))
                subtotal = (price * quantity).quantize(CENT)
                total += subtotal
                details.append(SaleDetail(uuid=identity(tid, "detail", f"{index}:{item.barcode}"),
                                          sale_id=sale_id, product=item, quantity=quantity, price=price, subtotal=subtotal))
                if not cancelled:
                    consumed[str(item.uuid)] += quantity
            method = rng.choices(["CASH", "CARD", "TRANSFER", "MIXED"], [45, 25, 20, 10])[0]
            if method == "MIXED":
                amount = (total / 2).quantize(CENT)
                payments = [{"method": "CASH", "amount": str(amount)}, {"method": "CARD", "amount": str(total - amount)}]
            else:
                payments = [{"method": method, "amount": str(total)}]
            sales.append(Sale(uuid=sale_id, tenant_id=tid, user=box.opened_by, cashbox=box, total=total,
                              payment_method=method, payments=payments, status="CANCELLED" if cancelled else "COMPLETED"))
            sale_times.append({"created_at": when})
            if not cancelled:
                cash[box.uuid] += sum((Decimal(p["amount"]) for p in payments if p["method"] == "CASH"), Decimal(0))
            usage = event(tid, "pos_sales", sale_id, when, f"sale:{sale_id}")
            audit("SALE", "SALE", sale_id, when, box.opened_by, {"usage_event": usage, "simulated": True}, f"sale:{index}")
            if cancelled:
                audit("UPDATE", "SALE", sale_id, when, box.opened_by,
                      {"status": "CANCELLED", "simulated": True}, f"cancel:{index}")
        insert_historical(Sale, sales, sale_times)
        SaleDetail.objects.bulk_create(details, batch_size=500)
        for box in boxes:
            if box.status == "CLOSED":
                box.expected_amount = box.initial_amount + cash[box.uuid]
                box.difference = Decimal("0.00")
                box.final_amount = box.expected_amount
            audit("CASHBOX", "CASHBOX", box.uuid, box.opened_at, box.opened_by,
                  {"event": "opened", "simulated": True}, f"box-open:{box.uuid}")
            if box.closed_at:
                audit("CASHBOX", "CASHBOX", box.uuid, box.closed_at, box.closed_by,
                      {"event": "closed", "simulated": True}, f"box-close:{box.uuid}")
        Cashbox.objects.bulk_update(boxes, ["expected_amount", "difference", "final_amount"], batch_size=300)
        # Record the opening inventory assumption without inventing inventory movement tables.
        for item in products:
            audit("CREATE", "PRODUCT", item.uuid, start, users[0],
                  {"initial_stock": str(Decimal(str(item.stock)) + consumed[str(item.uuid)]),
                   "final_seed_stock": str(item.stock), "simulated": True}, f"product:{item.uuid}")
        emails, email_times, extractions, extraction_times = [], [], [], []
        for month_index, (a, b, _) in enumerate(months(start, end)):
            when = a + (b - a) / 2
            related_box = box_map[when.astimezone(LOCAL).date(), 0]
            # Free has no paid email allowance. Both successful and failed sends consume.
            if plan not in {"free", "starter"}:
                for attempt in range(2):
                    eid = identity(tid, "email", f"{month_index}:{attempt}")
                    sent = attempt == 0
                    emails.append(EmailDelivery(uuid=eid, tenant_id=tid, notification_type="cashbox_opened",
                                                provider="django", status="SENT" if sent else "FAILED",
                                                subject="[SIMULADO] Apertura de caja", from_email="demo@example.invalid",
                                                to_emails=[users[0].email], recipient_count=1,
                                                external_id=f"demo:{eid}", sent_at=when if sent else None,
                                                error_message="" if sent else "Fallo de entrega simulado",
                                                related_entity="CASHBOX", related_entity_id=related_box.uuid,
                                                metadata={"simulated": True}))
                    email_times.append({"created_at": when, "updated_at": when})
                    key = f"cashbox-email-report:{related_box.uuid}:opened:manual:{eid}"
                    usage = event(tid, "cashbox_email_report", f"{related_box.uuid}:opened:manual", when, key)
                    audit("CASHBOX_EMAIL" if sent else "CASHBOX_EMAIL_FAILED", "CASHBOX", related_box.uuid,
                          when, related_box.opened_by, {"usage_event": usage, "delivery_id": str(eid)}, f"email:{eid}")
            if plan == "business_ai":
                for attempt in range(2):
                    eid = identity(tid, "extraction", f"{month_index}:{attempt}")
                    confirmed = attempt == 0
                    item = products[month_index % len(products)]
                    payload = {"products": [{"code": item.barcode, "description": item.name, "quantity": 2,
                                               "price": float(item.cost), "total": float(Decimal(str(item.cost)) * 2)}],
                               "date": when.date().isoformat(), "total": float(Decimal(str(item.cost)) * 2), "is_invoice": True}
                    extractions.append(DocumentExtraction(uuid=eid, tenant_id=tid,
                        status="confirmed" if confirmed else "failed", provider="simulated", model="demo-offline",
                        extracted_data=payload if confirmed else None, raw_response={"simulated": True},
                        attempts=1, confidence=Decimal("0.98") if confirmed else None,
                        processing_started_at=when, completed_at=when, confirmed_at=when if confirmed else None,
                        error_message=None if confirmed else "Documento ilegible simulado"))
                    extraction_times.append({"created_at": when, "updated_at": when})
                    if confirmed:
                        usage = event(tid, "document_extraction", eid, when, f"document-extraction:{eid}")
                        audit("CREATE", "TENANT_CONFIG", UUID(tid), when, users[0],
                              {"usage_event": usage, "extraction_id": str(eid)}, f"extraction:{eid}")
        insert_historical(EmailDelivery, emails, email_times)
        insert_historical(DocumentExtraction, extractions, extraction_times)
        insert_historical(AuditLog, audits, audit_times)
        counts = {"products": len(products), "users": 3, "suppliers": supplier_count, "registers": 2,
                  "cashboxes": len(boxes), "sales": len(sales), "details": len(details),
                  "emails": len(emails), "extractions": len(extractions), "audits": len(audits)}
        marker = AuditLog.objects.create(uuid=identity(tid, "marker", "complete"), tenant_id=tid,
            user=users[0], action="CREATE", entity="TENANT_CONFIG", entity_id=UUID(tid),
            metadata={"dataset_id": manifest["dataset_id"], "fingerprint": manifest["fingerprint"],
                      "counts": counts, "completed": True,
                      "identities": {"tenants.TenantConfig": [str(tid)],
                                     "users.User": [str(row.pk) for row in users],
                                     "products.Product": [str(row.pk) for row in products],
                                     "products.Category": [str(row.pk) for row in categories.values()],
                                     "suppliers.Supplier": [str(row.pk) for row in suppliers],
                                     "suppliers.ProductSupplier": [str(row.pk) for row in links],
                                     "cashbox.CashRegister": [str(row.pk) for row in registers],
                                     "cashbox.Cashbox": [str(row.pk) for row in boxes],
                                     "notifications.EmailDelivery": [str(row.pk) for row in emails],
                                     "document_extractor.DocumentExtraction": [str(row.pk) for row in extractions]}})
        AuditLog.objects.filter(pk=marker.pk).update(timestamp=end)


def result(manifest):
    usage, counts = [], {}
    for tenant in manifest["tenants"]:
        marker = check_conflict(manifest, tenant)
        if not marker or not marker.metadata.get("completed"):
            raise CommandError(f"Tenant {tenant['id']} has not completed loading.")
        counts[tenant["id"]] = marker.metadata["counts"]
        rows = AuditLog.objects.filter(tenant_id=tenant["id"], metadata__fingerprint=manifest["fingerprint"])
        if rows.count() != marker.metadata["counts"]["audits"] + 1:
            raise CommandError(f"Seed audit history is incomplete for {tenant['id']}.")
        for metadata in rows.values_list("metadata", flat=True).iterator(chunk_size=1000):
            if "usage_event" in metadata:
                usage.append(metadata["usage_event"])
        # Only check presence: subsequent legitimate sales/stock edits must not be reset.
        ids = [identity(tenant["id"], "sale", i) for i in range(marker.metadata["counts"]["sales"])]
        found = sum(Sale.objects.filter(tenant_id=tenant["id"], pk__in=ids[i:i + 500]).count()
                    for i in range(0, len(ids), 500))
        if found != len(ids):
            raise CommandError(f"Seed sales are missing for {tenant['id']}.")
        verify_tenant(tenant["id"], marker, ids)
    return {"usage_events": sorted(usage, key=lambda item: (item["occurred_at"], item["id"])), "counts": counts}


def verify_tenant(tid, marker, sale_ids):
    """Check relationships and accounting, without requiring mutable stock or passwords to match."""
    tid = UUID(str(tid))
    for label, ids in marker.metadata["identities"].items():
        model = apps.get_model(label)
        for offset in range(0, len(ids), 500):
            batch = ids[offset:offset + 500]
            rows = list(model._base_manager.filter(pk__in=batch))
            if len(rows) != len(batch):
                raise CommandError(f"Missing seeded {label} rows for {tid}.")
            for row in rows:
                if hasattr(row, "tenant_id") and row.tenant_id != tid:
                    raise CommandError(f"Cross-tenant seeded {label} row.")
                if isinstance(row, ProductSupplier):
                    if row.product.tenant_id != tid or row.supplier.tenant_id != tid:
                        raise CommandError("Cross-tenant supplier link.")
                if isinstance(row, Product) and row.category_id and row.category.tenant_id != tid:
                    raise CommandError("Cross-tenant product category.")
    seeded_details = 0
    for offset in range(0, len(sale_ids), 500):
        rows = Sale.objects.filter(pk__in=sale_ids[offset:offset + 500]).select_related(
            "cashbox", "user").prefetch_related("details__product")
        for sale in rows:
            details = list(sale.details.all())
            seeded_details += len(details)
            if not details or sum((d.subtotal for d in details), Decimal(0)) != sale.total:
                raise CommandError(f"Invalid sale detail total: {sale.pk}.")
            if any(d.subtotal != (d.price * d.quantity).quantize(CENT) or d.product.tenant_id != tid for d in details):
                raise CommandError(f"Invalid sale detail relationship or amount: {sale.pk}.")
            if sum((Decimal(payment["amount"]) for payment in sale.payments), Decimal(0)) != sale.total:
                raise CommandError(f"Invalid sale payment total: {sale.pk}.")
            box = sale.cashbox
            if sale.user.tenant_id != tid or box.tenant_id != tid or sale.user_id != box.opened_by_id:
                raise CommandError(f"Invalid sale ownership: {sale.pk}.")
            if sale.created_at < box.opened_at or (box.closed_at and sale.created_at >= box.closed_at):
                raise CommandError(f"Sale outside its cashbox session: {sale.pk}.")
    if seeded_details != marker.metadata["counts"]["details"]:
        raise CommandError(f"Seed sale details are incomplete for {tid}.")
    box_ids = marker.metadata["identities"]["cashbox.Cashbox"]
    for offset in range(0, len(box_ids), 500):
        boxes = Cashbox.objects.filter(pk__in=box_ids[offset:offset + 500]).select_related(
            "register", "opened_by", "closed_by").prefetch_related("sales")
        for box in boxes:
            if box.register.tenant_id != tid or box.opened_by.tenant_id != tid or (
                    box.closed_by and box.closed_by.tenant_id != tid):
                raise CommandError(f"Invalid cashbox ownership: {box.pk}.")
            if box.status == "CLOSED":
                amount = sum((Decimal(payment["amount"]) for sale in box.sales.all()
                              if sale.status == "COMPLETED" for payment in sale.payments
                              if payment["method"] == "CASH"), Decimal(0))
                if (box.expected_amount != box.initial_amount + amount or box.final_amount is None
                        or box.difference != box.final_amount - box.expected_amount):
                    raise CommandError(f"Cashbox does not reconcile: {box.pk}.")
