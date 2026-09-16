from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from uuid import NAMESPACE_URL, uuid5

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from apps.arca.models import FiscalOutboxRequest
from apps.arca.outbox import create_sale_fiscal_request
from apps.audit.models import AuditLog
from apps.cashbox.models import Cashbox
from apps.mercado_pago.client import PlatformMercadoPagoClient
from apps.mercado_pago.models import MercadoPagoBillingRelease, MercadoPagoOrder
from apps.platform_billing.client import PlatformBillingError
from apps.platform_billing.enforcement import (
    BillingEnforcementError,
    commit_billing_reservation,
    release_billing_reservation,
    reserve_billing_usage,
)
from apps.products.models import Product
from apps.sales.models import Sale, SaleDetail
from apps.tenants.models import Tenant


FINAL_REMOTE_PAID = {"paid", "approved", "accredited"}
FINAL_REMOTE_FAILED = {"failed", "rejected", "cancelled", "canceled", "expired"}
FINAL_REMOTE_REFUNDED = {"refunded"}
logger = logging.getLogger(__name__)


class MercadoPagoConflict(Exception):
    pass


class CanonicalOrderMismatch(Exception):
    pass


def ensure_sale_replay_access(request, sale):
    """Apply the same object boundary used by employee sale reads."""
    if request.user.role != "EMPLOYEE":
        return
    if (
        sale.user_id != request.user.pk
        or sale.cashbox.opened_by_id != request.user.pk
        or sale.cashbox.status != Cashbox.Status.OPEN
    ):
        raise NotFound("Sale not found.")


def request_fingerprint(payload) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def stable_operation_key(namespace, tenant_id, frontend_key):
    digest = hashlib.sha256(f"{tenant_id}:{frontend_key}".encode("utf-8")).hexdigest()
    return f"mp-{namespace}:{digest}"


def create_external_sale(*, request, validated_data, fingerprint, idempotency_key, client=None):
    if not idempotency_key or len(idempotency_key) > 160:
        raise serializers.ValidationError({"X-Idempotency-Key": "A non-empty key of at most 160 characters is required."})
    idempotency_key = idempotency_key.strip()
    existing = MercadoPagoOrder.objects.select_related("sale__cashbox").filter(
        tenant_id=request.tenant_id, frontend_idempotency_key=idempotency_key,
    ).first()
    if existing:
        ensure_sale_replay_access(request, existing.sale)
        if existing.request_fingerprint != fingerprint:
            raise MercadoPagoConflict("The idempotency key was already used with a different request.")
        return existing.sale, True

    external_payment = validated_data["external_payment"]
    sale_uuid = uuid5(
        NAMESPACE_URL,
        f"postas:mercado-pago:{request.tenant_id}:{idempotency_key}",
    )
    billing_key = stable_operation_key("billing", request.tenant_id, idempotency_key)
    release_task, _ = MercadoPagoBillingRelease.objects.update_or_create(
        idempotency_key=billing_key,
        defaults={
            "tenant_id": request.tenant_id,
            "attempt_count": 0,
            "next_attempt_at": timezone.now() + timedelta(minutes=5),
            "locked_at": None,
            "last_error": "",
        },
    )
    try:
        reserve_response = reserve_billing_usage(
            request.tenant_id, "pos_sales", amount=1, external_id=sale_uuid,
            idempotency_key=billing_key,
            metadata={"sale": str(sale_uuid), "payment_method": external_payment["method"]},
        )
    except BillingEnforcementError as exc:
        if exc.status_code < 500:
            release_task.delete()
        raise
    try:
        sale, order = _persist_external_sale(
            request=request, validated_data=validated_data, sale_uuid=sale_uuid,
            fingerprint=fingerprint, idempotency_key=idempotency_key,
            billing_key=billing_key, reserve_response=reserve_response,
        )
    except IntegrityError:
        existing = MercadoPagoOrder.objects.select_related("sale__cashbox").filter(
            tenant_id=request.tenant_id, frontend_idempotency_key=idempotency_key,
        ).first()
        if existing:
            ensure_sale_replay_access(request, existing.sale)
            release_task.delete()
            if existing.request_fingerprint == fingerprint:
                return existing.sale, True
            raise MercadoPagoConflict(
                "The idempotency key was already used with a different request."
            )
        _safe_release(request.tenant_id, billing_key)
        raise MercadoPagoConflict("The idempotency key was already used with a different request.")
    except Exception:
        MercadoPagoBillingRelease.objects.filter(uuid=release_task.uuid).update(
            next_attempt_at=timezone.now(),
        )
        _safe_release(request.tenant_id, billing_key)
        raise

    release_task.delete()
    attempt_create_order(order.uuid, client=client)
    sale.refresh_from_db()
    return sale, False


@transaction.atomic
def _persist_external_sale(*, request, validated_data, sale_uuid, fingerprint, idempotency_key, billing_key, reserve_response):
    Tenant.objects.select_for_update().get(uuid=request.tenant_id)
    cashbox = Cashbox.objects.select_for_update().filter(
        uuid=validated_data["cashbox"].uuid, tenant_id=request.tenant_id,
        opened_by=request.user, status=Cashbox.Status.OPEN,
    ).first()
    if cashbox is None:
        raise serializers.ValidationError("The user's cashbox is no longer open.")

    aggregated = {}
    for item in validated_data["items"]:
        product_id = item["product_id"]
        aggregated[product_id] = aggregated.get(product_id, Decimal("0")) + item["quantity"]
    products = Product.objects.select_for_update().filter(
        tenant_id=request.tenant_id, uuid__in=aggregated,
    ).order_by("uuid")
    product_map = {product.uuid: product for product in products}
    if len(product_map) != len(aggregated):
        raise serializers.ValidationError("One or more products are no longer available.")

    total = Decimal("0")
    details = []
    for product_id in sorted(aggregated, key=str):
        product = product_map[product_id]
        quantity = aggregated[product_id]
        if product.stock < quantity:
            raise serializers.ValidationError(
                f"Insufficient stock for {product.name}. Available: {product.stock}, requested: {quantity}."
            )
        subtotal = product.price * quantity
        total += subtotal
        details.append((product, quantity, subtotal))

    payments = validated_data["payments"]
    if sum((payment["amount"] for payment in payments), Decimal("0")) != total:
        raise serializers.ValidationError("The payment amounts must match the current sale total exactly.")
    external = validated_data["external_payment"]
    register = cashbox.register
    if register is None or not register.active:
        raise serializers.ValidationError("The open cashbox has no active cash register.")
    if external["method"] == Sale.PaymentMethod.POINT and not register.mercado_pago_terminal_id:
        raise serializers.ValidationError("The cash register has no Mercado Pago Point terminal associated.")
    if (
        external["method"] == Sale.PaymentMethod.QR
        and not register.mercado_pago_external_pos_id
    ):
        raise serializers.ValidationError("The cash register has no Mercado Pago QR POS associated.")

    payment_method = payments[0]["method"] if len(payments) == 1 else Sale.PaymentMethod.MIXED
    sale = Sale.objects.create(
        uuid=sale_uuid, tenant_id=request.tenant_id, user=request.user, cashbox=cashbox,
        total=total, payment_method=payment_method,
        payments=[{"method": item["method"], "amount": str(item["amount"])} for item in payments],
        status=Sale.Status.PENDING,
    )
    SaleDetail.objects.bulk_create([
        SaleDetail(sale=sale, product=product, quantity=quantity, price=product.price, subtotal=subtotal)
        for product, quantity, subtotal in details
    ])
    for product, quantity, _subtotal in details:
        product.stock -= quantity
        product.save(update_fields=["stock"])

    reservation_id = reserve_response.get("reservation_id") or reserve_response.get("id") or ""
    order = MercadoPagoOrder.objects.create(
        tenant_id=request.tenant_id, sale=sale, amount=external["amount"],
        order_type=external["method"], external_reference=str(sale.uuid),
        terminal_id=register.mercado_pago_terminal_id,
        pos_id=register.mercado_pago_pos_id,
        external_pos_id=register.mercado_pago_external_pos_id,
        frontend_idempotency_key=idempotency_key, request_fingerprint=fingerprint,
        create_idempotency_key=stable_operation_key("create", request.tenant_id, idempotency_key),
        billing_reservation_key=billing_key, billing_reservation_id=str(reservation_id),
        next_retry_at=timezone.now(),
    )
    return sale, order


def attempt_create_order(order_id, *, client=None):
    order = MercadoPagoOrder.objects.select_related("sale").get(uuid=order_id)
    if order.external_order_id:
        return order
    payload = {
        "type": order.order_type.lower(), "amount": str(order.amount),
        "currency": order.currency, "external_reference": order.external_reference,
    }
    if order.order_type == MercadoPagoOrder.Type.POINT:
        payload["terminal_id"] = order.terminal_id
    else:
        payload.update({"mode": "dynamic", "pos_id": order.pos_id, "external_pos_id": order.external_pos_id})
    try:
        response = (client or PlatformMercadoPagoClient()).create_order(
            order.tenant_id,
            payload,
            idempotency_key=order.create_idempotency_key,
        )
    except PlatformBillingError as exc:
        _record_order_retry(order, "create_uncertain" if exc.status_code == 504 else "create_failed", exc.message)
        return order
    normalized = _unwrap_order(response)
    external_id = normalized.get("id") or normalized.get("order_id")
    if not external_id:
        _record_order_retry(order, "invalid_create_response", "Platform did not return an order id.")
        return order
    order.external_order_id = str(external_id)
    order.remote_status = str(normalized.get("status") or "pending")
    order.remote_status_detail = str(normalized.get("status_detail") or "")[:160]
    order.collector_id = str(normalized.get("collector_id") or normalized.get("user_id") or "")
    order.currency = str(normalized.get("currency") or normalized.get("currency_id") or order.currency)
    order.live_mode = bool(normalized.get("live_mode", order.live_mode))
    order.qr_data = str(normalized.get("qr_data") or normalized.get("qr", {}).get("data") or "")
    order.expires_at = _parse_date(normalized.get("expiration_date") or normalized.get("expires_at"))
    order.state = MercadoPagoOrder.State.PENDING
    order.next_retry_at = timezone.now() + timedelta(seconds=10)
    order.last_error_code = ""
    order.last_error_message = ""
    order.save()
    return order


def reconcile_order(order_id, *, client=None):
    order = MercadoPagoOrder.objects.select_related("sale").get(uuid=order_id)
    if not order.external_order_id:
        return attempt_create_order(order.uuid, client=client)
    reconcile_version = _next_reconcile_version(order.uuid)
    try:
        response = (client or PlatformMercadoPagoClient()).get_order(order.tenant_id, order.external_order_id)
        remote = _unwrap_order(response)
        _validate_canonical_order(order, remote)
    except PlatformBillingError as exc:
        _record_order_retry(
            order,
            "canonical_fetch_failed",
            exc.message,
            expected_version=reconcile_version,
        )
        return MercadoPagoOrder.objects.get(uuid=order.uuid)
    except CanonicalOrderMismatch as exc:
        _record_order_retry(
            order,
            "canonical_mismatch",
            str(exc),
            expected_version=reconcile_version,
        )
        return MercadoPagoOrder.objects.get(uuid=order.uuid)

    status_value = str(remote.get("status") or "").lower()
    payment_status = _payment_status(remote)
    MercadoPagoOrder.objects.filter(
        uuid=order.uuid,
        reconcile_version=reconcile_version,
    ).update(
        remote_status=status_value,
        remote_status_detail=str(remote.get("status_detail") or "")[:160],
        qr_data=str(
            remote.get("qr_data")
            or remote.get("qr", {}).get("data")
            or order.qr_data
        ),
        updated_at=timezone.now(),
    )

    payment_status_detail = str(remote.get("payment_status_detail") or "").lower()
    if status_value in FINAL_REMOTE_REFUNDED or payment_status == "refunded":
        return _finalize_order(
            order.uuid,
            MercadoPagoOrder.State.REFUNDED,
            expected_version=reconcile_version,
        )
    if status_value in FINAL_REMOTE_PAID or (
        status_value == "processed"
        and (payment_status in FINAL_REMOTE_PAID or payment_status_detail in FINAL_REMOTE_PAID)
    ):
        return _finalize_order(
            order.uuid,
            MercadoPagoOrder.State.PAID,
            expected_version=reconcile_version,
        )
    if status_value in FINAL_REMOTE_FAILED:
        final = MercadoPagoOrder.State.EXPIRED if status_value == "expired" else (
            MercadoPagoOrder.State.CANCELLED if status_value in {"cancelled", "canceled"} else MercadoPagoOrder.State.FAILED
        )
        return _finalize_order(order.uuid, final, expected_version=reconcile_version)

    if order.state not in {MercadoPagoOrder.State.PAID, MercadoPagoOrder.State.REFUNDED, MercadoPagoOrder.State.CANCELLED}:
        if order.state == MercadoPagoOrder.State.ACTION_REQUIRED:
            order.state = MercadoPagoOrder.State.ACTION_REQUIRED
        elif order.refund_idempotency_key:
            order.state = MercadoPagoOrder.State.REFUND_PENDING
        elif order.cancel_idempotency_key:
            order.state = MercadoPagoOrder.State.CANCEL_REQUESTED
        else:
            order.state = MercadoPagoOrder.State.PENDING
        MercadoPagoOrder.objects.filter(
            uuid=order.uuid,
            reconcile_version=reconcile_version,
            state__in=MercadoPagoOrder.ACTIVE_STATES,
        ).update(
            state=order.state,
            next_retry_at=timezone.now() + timedelta(seconds=15),
            last_error_code="",
            last_error_message="",
            updated_at=timezone.now(),
        )
    return MercadoPagoOrder.objects.get(uuid=order.uuid)


@transaction.atomic
def _next_reconcile_version(order_id):
    order = MercadoPagoOrder.objects.select_for_update().get(uuid=order_id)
    order.reconcile_version += 1
    order.save(update_fields=["reconcile_version", "updated_at"])
    return order.reconcile_version


@transaction.atomic
def _finalize_order(order_id, final_state, *, expected_version):
    candidate = MercadoPagoOrder.objects.only("tenant_id", "sale_id").get(uuid=order_id)
    Tenant.objects.select_for_update().get(uuid=candidate.tenant_id)
    cashbox_id = Sale.objects.only("cashbox_id").get(uuid=candidate.sale_id).cashbox_id
    Cashbox.objects.select_for_update().get(uuid=cashbox_id, tenant_id=candidate.tenant_id)
    sale = Sale.objects.select_for_update().select_related("user").get(uuid=candidate.sale_id, tenant_id=candidate.tenant_id)
    order = MercadoPagoOrder.objects.select_for_update().get(uuid=order_id, tenant_id=candidate.tenant_id)
    if order.reconcile_version != expected_version:
        return order

    if final_state == MercadoPagoOrder.State.PAID:
        if sale.status == Sale.Status.CANCELLED or order.state == MercadoPagoOrder.State.REFUNDED:
            return order
        commit_billing_reservation(order.tenant_id, idempotency_key=order.billing_reservation_key)
        sale.status = Sale.Status.COMPLETED
        sale.save(update_fields=["status"])
        order.state = MercadoPagoOrder.State.PAID
        order.next_retry_at = None
        order.save(update_fields=["state", "next_retry_at", "updated_at"])
        if not FiscalOutboxRequest.objects.filter(sale=sale).exists():
            create_sale_fiscal_request(sale, sale.user)
        _audit_sale(sale, "MP_PAID")
        return order

    if (
        final_state != MercadoPagoOrder.State.REFUNDED
        and (
            sale.status == Sale.Status.COMPLETED
            or order.state in {MercadoPagoOrder.State.PAID, MercadoPagoOrder.State.REFUNDED}
        )
    ):
        return order

    if sale.status == Sale.Status.PENDING:
        release_billing_reservation(order.tenant_id, idempotency_key=order.billing_reservation_key)
    if not order.stock_restored:
        details = list(sale.details.order_by("product_id"))
        products = Product.all_objects.select_for_update().filter(
            tenant_id=sale.tenant_id, uuid__in=[detail.product_id for detail in details],
        ).order_by("uuid")
        product_map = {product.uuid: product for product in products}
        for detail in details:
            product = product_map[detail.product_id]
            product.stock += detail.quantity
            product.save(update_fields=["stock"])
        order.stock_restored = True
    sale.status = Sale.Status.CANCELLED
    sale.save(update_fields=["status"])
    order.state = final_state
    order.next_retry_at = None
    order.save(update_fields=["state", "stock_restored", "next_retry_at", "updated_at"])
    _audit_sale(sale, f"MP_{final_state}")
    return order


def _validate_canonical_order(order, remote):
    checks = [
        (str(remote.get("id") or remote.get("order_id")), str(order.external_order_id), "order id"),
        (str(remote.get("external_reference") or remote.get("reference")), order.external_reference, "reference"),
        (str(remote.get("type") or remote.get("order_type")).upper(), order.order_type, "type"),
        (str(remote.get("currency") or remote.get("currency_id")), order.currency, "currency"),
    ]
    for actual, expected, label in checks:
        if actual != str(expected):
            raise CanonicalOrderMismatch(f"Unexpected {label}.")
    try:
        amount = Decimal(str(_remote_amount(remote)))
    except (InvalidOperation, TypeError):
        raise CanonicalOrderMismatch("Invalid amount.")
    if amount != order.amount:
        raise CanonicalOrderMismatch("Unexpected amount.")
    collector = str(remote.get("collector_id") or remote.get("user_id") or "")
    if not collector or (order.collector_id and collector != order.collector_id):
        raise CanonicalOrderMismatch("Unexpected collector.")
    if "live_mode" not in remote or bool(remote["live_mode"]) != order.live_mode:
        raise CanonicalOrderMismatch("Unexpected environment.")


def _remote_amount(remote):
    for key in ("amount", "total_amount", "total"):
        if remote.get(key) is not None:
            return remote[key]
    transactions = remote.get("transactions") or {}
    payments = transactions.get("payments") or remote.get("payments") or []
    if payments and isinstance(payments[0], dict):
        return payments[0].get("amount") or payments[0].get("total_paid_amount")
    return None


def _payment_status(remote):
    if remote.get("payment_status"):
        return str(remote["payment_status"]).lower()
    payment = remote.get("payment") or {}
    if isinstance(payment, dict) and payment.get("status"):
        return str(payment["status"]).lower()
    payments = (remote.get("transactions") or {}).get("payments") or remote.get("payments") or []
    if payments and isinstance(payments[0], dict):
        return str(payments[0].get("status") or "").lower()
    return ""


def _unwrap_order(response):
    nested = response.get("order") if isinstance(response, dict) else None
    return nested if isinstance(nested, dict) else response


def _parse_date(value):
    if not value:
        return None
    if hasattr(value, "tzinfo"):
        return value
    parsed = parse_datetime(str(value))
    return parsed


def _record_order_retry(order, code, message, *, expected_version=None):
    if expected_version is not None:
        updated = MercadoPagoOrder.objects.filter(
            uuid=order.uuid,
            reconcile_version=expected_version,
        ).update(
            state=MercadoPagoOrder.State.ERROR,
            retry_count=order.retry_count + 1,
            next_retry_at=timezone.now()
            + timedelta(seconds=min(300, 5 * (2 ** min(order.retry_count + 1, 6)))),
            locked_at=None,
            last_error_code=code,
            last_error_message=str(message)[:1000],
            updated_at=timezone.now(),
        )
        if updated:
            order.refresh_from_db()
        return
    order.state = MercadoPagoOrder.State.ERROR
    order.retry_count += 1
    order.next_retry_at = timezone.now() + timedelta(seconds=min(300, 5 * (2 ** min(order.retry_count, 6))))
    order.locked_at = None
    order.last_error_code = code
    order.last_error_message = str(message)[:1000]
    order.save(update_fields=["state", "retry_count", "next_retry_at", "locked_at", "last_error_code", "last_error_message", "updated_at"])


def _safe_release(tenant_id, billing_key):
    try:
        release_billing_reservation(tenant_id, idempotency_key=billing_key)
        MercadoPagoBillingRelease.objects.filter(idempotency_key=billing_key).delete()
    except Exception as exc:
        logger.error(
            "Failed to release Mercado Pago billing reservation tenant=%s key=%s error=%s",
            tenant_id,
            billing_key,
            type(exc).__name__,
        )


def _audit_sale(sale, event):
    AuditLog.objects.create(
        tenant_id=sale.tenant_id, user=sale.user, action="SALE", entity="SALE",
        entity_id=sale.uuid, metadata={"action": event, "cashbox_id": str(sale.cashbox_id)},
    )
