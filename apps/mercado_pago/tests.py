import hashlib
import hmac
import time
import uuid
from decimal import Decimal
from unittest.mock import Mock, patch

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.arca.models import FiscalOutboxRequest
from apps.cashbox.models import Cashbox, CashRegister
from apps.mercado_pago.client import PlatformMercadoPagoClient
from apps.mercado_pago.models import (
    MercadoPagoBillingRelease,
    MercadoPagoOrder,
    MercadoPagoWebhookInbox,
)
from apps.mercado_pago.services import _finalize_order, reconcile_order
from apps.mercado_pago.worker import MercadoPagoWorker
from apps.platform_billing.client import PlatformBillingError
from apps.platform_billing.enforcement import BillingEnforcementError
from apps.products.models import Product
from apps.sales.models import Sale
from apps.tenants.models import Tenant, TenantConfig
from apps.users.models import User


class MercadoPagoSaleTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(uuid=uuid.uuid4(), name="MP tenant")
        TenantConfig.objects.create(
            tenant=self.tenant,
            automatic_invoicing_enabled=True,
        )
        self.employee = User.objects.create_user(
            tenant_id=self.tenant.uuid,
            username="employee",
            email="employee@example.com",
            password="secret",
            role=User.Role.EMPLOYEE,
        )
        self.owner = User.objects.create_user(
            tenant_id=self.tenant.uuid,
            username="owner",
            email="owner@example.com",
            password="secret",
            role=User.Role.OWNER,
        )
        self.register = CashRegister.objects.create(
            tenant_id=self.tenant.uuid,
            name="Principal",
            mercado_pago_terminal_id="POINT-1",
            mercado_pago_pos_id="10",
            mercado_pago_external_pos_id="POS-1",
        )
        self.cashbox = Cashbox.objects.create(
            tenant_id=self.tenant.uuid,
            register=self.register,
            opened_by=self.employee,
            initial_amount=Decimal("100.00"),
        )
        self.product = Product.objects.create(
            tenant_id=self.tenant.uuid,
            name="Product",
            price=Decimal("1500.00"),
            cost=Decimal("800.00"),
            stock=Decimal("10.000"),
        )
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self._token(self.employee)}"
        )

    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    def test_point_sale_returns_202_reserves_stock_and_replays_idempotently(
        self, reserve, client_class
    ):
        reserve.return_value = {"allowed": True, "reservation_id": str(uuid.uuid4())}
        client_class.return_value.create_order.return_value = {
            "id": "ORDER-1",
            "type": "point",
            "status": "created",
            "external_reference": "unused-by-create",
            "collector_id": "COLLECTOR-1",
            "currency": "ARS",
            "live_mode": False,
            "total_amount": "1500.00",
        }
        body = self._sale_body("POINT", "1500.00")

        first = self.client.post(
            "/api/v1/sales/", body, format="json", HTTP_X_IDEMPOTENCY_KEY="sale-key"
        )
        replay = self.client.post(
            "/api/v1/sales/", body, format="json", HTTP_X_IDEMPOTENCY_KEY="sale-key"
        )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(first.data["uuid"], replay.data["uuid"])
        self.assertEqual(first.data["status"], Sale.Status.PENDING)
        self.assertEqual(first.data["mercado_pago"]["state"], MercadoPagoOrder.State.PENDING)
        self.assertEqual(Sale.objects.filter(tenant_id=self.tenant.uuid).count(), 1)
        reserve.assert_called_once()
        client_class.return_value.create_order.assert_called_once()
        call = client_class.return_value.create_order.call_args
        self.assertLessEqual(len(call.kwargs["idempotency_key"]), 160)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, Decimal("9.000"))

    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    def test_employee_replay_does_not_expose_another_cashiers_sale(
        self, reserve, client_class
    ):
        order = self._create_pending_order(
            reserve, client_class, key="cashier-scoped-replay"
        )
        other_employee = User.objects.create_user(
            tenant_id=self.tenant.uuid,
            username="other-employee",
            email="other-employee@example.com",
            password="secret",
            role=User.Role.EMPLOYEE,
        )
        other_register = CashRegister.objects.create(
            tenant_id=self.tenant.uuid,
            name="Secondary register",
        )
        Cashbox.objects.create(
            tenant_id=self.tenant.uuid,
            register=other_register,
            opened_by=other_employee,
            initial_amount=Decimal("0.00"),
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self._token(other_employee)}"
        )

        response = self.client.post(
            "/api/v1/sales/",
            self._sale_body("POINT", "1500.00"),
            format="json",
            HTTP_X_IDEMPOTENCY_KEY="cashier-scoped-replay",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(str(response.data["detail"]), "Sale not found.")
        self.assertNotEqual(response.data.get("uuid"), str(order.sale_id))
        self.assertEqual(Sale.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, Decimal("9.000"))
        reserve.assert_called_once()
        client_class.return_value.create_order.assert_called_once()

    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    def test_employee_replay_does_not_expose_sale_after_cashbox_closes(
        self, reserve, client_class
    ):
        order = self._create_pending_order(
            reserve, client_class, key="closed-cashbox-replay"
        )
        Cashbox.objects.filter(uuid=self.cashbox.uuid).update(
            status=Cashbox.Status.CLOSED
        )

        response = self.client.post(
            "/api/v1/sales/",
            self._sale_body("POINT", "1500.00"),
            format="json",
            HTTP_X_IDEMPOTENCY_KEY="closed-cashbox-replay",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(str(response.data["detail"]), "Sale not found.")
        self.assertNotEqual(response.data.get("uuid"), str(order.sale_id))
        self.assertEqual(Sale.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, Decimal("9.000"))
        reserve.assert_called_once()
        client_class.return_value.create_order.assert_called_once()

    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    def test_frontend_idempotency_key_rejects_a_different_request(
        self, reserve, client_class
    ):
        reserve.return_value = {"allowed": True, "reservation_id": str(uuid.uuid4())}
        client_class.return_value.create_order.return_value = {
            "id": "ORDER-IDEMPOTENCY",
            "status": "created",
            "collector_id": "COLLECTOR-1",
            "currency": "ARS",
            "live_mode": False,
            "total_amount": "1500.00",
        }
        first = self.client.post(
            "/api/v1/sales/",
            self._sale_body("POINT", "1500.00"),
            format="json",
            HTTP_X_IDEMPOTENCY_KEY="same-frontend-key",
        )
        changed = self._sale_body("POINT", "1500.00")
        changed["items"][0]["quantity"] = "2.000"

        conflict = self.client.post(
            "/api/v1/sales/",
            changed,
            format="json",
            HTTP_X_IDEMPOTENCY_KEY="same-frontend-key",
        )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.data["code"], "idempotency_conflict")
        self.assertEqual(Sale.objects.count(), 1)
        reserve.assert_called_once()
        client_class.return_value.create_order.assert_called_once()

    @patch("apps.mercado_pago.services.release_billing_reservation")
    @patch("apps.mercado_pago.services._persist_external_sale")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    def test_integrity_recovery_conflict_never_releases_winning_reservation(
        self, reserve, persist, release
    ):
        reservation_id = str(uuid.uuid4())
        reserve.return_value = {
            "allowed": True,
            "status": "active",
            "reservation_id": reservation_id,
        }

        def create_race_winner(**kwargs):
            winner_sale = Sale.objects.create(
                uuid=kwargs["sale_uuid"],
                tenant_id=self.tenant.uuid,
                user=self.employee,
                cashbox=self.cashbox,
                total=Decimal("1500.00"),
                payment_method=Sale.PaymentMethod.POINT,
                payments=[{"method": "POINT", "amount": "1500.00"}],
                status=Sale.Status.PENDING,
            )
            MercadoPagoOrder.objects.create(
                tenant_id=self.tenant.uuid,
                sale=winner_sale,
                amount=Decimal("1500.00"),
                order_type=MercadoPagoOrder.Type.POINT,
                external_reference=str(winner_sale.uuid),
                frontend_idempotency_key="integrity-race-key",
                request_fingerprint="winner-used-a-different-payload",
                create_idempotency_key="winning-create-key",
                billing_reservation_key=kwargs["billing_key"],
                billing_reservation_id=reservation_id,
            )
            raise IntegrityError("simulated unique-key race")

        persist.side_effect = create_race_winner

        response = self.client.post(
            "/api/v1/sales/",
            self._sale_body("POINT", "1500.00"),
            format="json",
            HTTP_X_IDEMPOTENCY_KEY="integrity-race-key",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "idempotency_conflict")
        winner = MercadoPagoOrder.objects.get(
            tenant_id=self.tenant.uuid,
            frontend_idempotency_key="integrity-race-key",
        )
        self.assertEqual(winner.billing_reservation_id, reservation_id)
        self.assertEqual(winner.state, MercadoPagoOrder.State.CREATING)
        release.assert_not_called()

    def test_external_sale_requires_key_and_exact_total(self):
        missing = self.client.post(
            "/api/v1/sales/", self._sale_body("QR", "1500.00"), format="json"
        )
        mismatch = self.client.post(
            "/api/v1/sales/",
            self._sale_body("QR", "1499.00"),
            format="json",
            HTTP_X_IDEMPOTENCY_KEY="mismatch",
        )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(Sale.objects.count(), 0)

    def test_sale_rejects_more_than_one_external_payment_line(self):
        response = self.client.post(
            "/api/v1/sales/",
            {
                "payments": [
                    {"method": "POINT", "amount": "750.00"},
                    {"method": "QR", "amount": "750.00"},
                ],
                "items": [
                    {"product_id": str(self.product.uuid), "quantity": "1.000"}
                ],
            },
            format="json",
            HTTP_X_IDEMPOTENCY_KEY="two-external-lines",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Sale.objects.count(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, Decimal("10.000"))

    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    def test_mixed_qr_sale_returns_qr_data(self, reserve, client_class):
        reserve.return_value = {"allowed": True, "reservation_id": str(uuid.uuid4())}
        client_class.return_value.create_order.return_value = {
            "id": "ORDER-QR",
            "status": "created",
            "collector_id": "COLLECTOR-1",
            "currency": "ARS",
            "live_mode": False,
            "total_amount": "1000.00",
            "qr_data": "000201010212...",
        }
        body = {
            "payments": [
                {"method": "CASH", "amount": "500.00"},
                {"method": "QR", "amount": "1000.00"},
            ],
            "items": [{"product_id": str(self.product.uuid), "quantity": "1.000"}],
        }

        response = self.client.post(
            "/api/v1/sales/", body, format="json", HTTP_X_IDEMPOTENCY_KEY="qr-key"
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["payment_method"], Sale.PaymentMethod.MIXED)
        self.assertEqual(response.data["mercado_pago"]["qr_data"], "000201010212...")
        payload = client_class.return_value.create_order.call_args.args[1]
        self.assertEqual(payload["type"], "qr")
        self.assertEqual(payload["external_pos_id"], "POS-1")

    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    @patch("apps.mercado_pago.services.commit_billing_reservation")
    def test_canonical_accredited_payment_commits_billing_and_creates_arca(
        self, commit, reserve, client_class
    ):
        order = self._create_pending_order(reserve, client_class, key="paid-key")
        canonical = self._canonical(order, status="processed")
        canonical["payment_status"] = "processed"
        canonical["payment_status_detail"] = "accredited"
        remote = Mock()
        remote.get_order.return_value = canonical

        reconcile_order(order.uuid, client=remote)

        order.refresh_from_db()
        order.sale.refresh_from_db()
        self.assertEqual(order.state, MercadoPagoOrder.State.PAID)
        self.assertEqual(order.sale.status, Sale.Status.COMPLETED)
        commit.assert_called_once_with(
            order.tenant_id, idempotency_key=order.billing_reservation_key
        )
        self.assertTrue(FiscalOutboxRequest.objects.filter(sale=order.sale).exists())

    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    @patch("apps.mercado_pago.services.release_billing_reservation")
    def test_failed_order_releases_billing_and_restores_stock_once(
        self, release, reserve, client_class
    ):
        order = self._create_pending_order(reserve, client_class, key="failed-key")
        remote = Mock()
        remote.get_order.return_value = self._canonical(order, status="failed")

        reconcile_order(order.uuid, client=remote)
        reconcile_order(order.uuid, client=remote)

        order.refresh_from_db()
        order.sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.state, MercadoPagoOrder.State.FAILED)
        self.assertEqual(order.sale.status, Sale.Status.CANCELLED)
        self.assertTrue(order.stock_restored)
        self.assertEqual(self.product.stock, Decimal("10.000"))
        release.assert_called_once_with(
            order.tenant_id, idempotency_key=order.billing_reservation_key
        )

    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    @patch("apps.mercado_pago.services.release_billing_reservation")
    @patch("apps.mercado_pago.services.commit_billing_reservation")
    def test_late_failed_status_does_not_revert_an_accredited_sale(
        self, commit, release, reserve, client_class
    ):
        order = self._create_pending_order(reserve, client_class, key="out-of-order")
        remote = Mock()
        paid = self._canonical(order, status="processed")
        paid.update(payment_status="processed", payment_status_detail="accredited")
        remote.get_order.return_value = paid
        reconcile_order(order.uuid, client=remote)

        remote.get_order.return_value = self._canonical(order, status="failed")
        reconcile_order(order.uuid, client=remote)

        order.refresh_from_db()
        order.sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.state, MercadoPagoOrder.State.PAID)
        self.assertEqual(order.sale.status, Sale.Status.COMPLETED)
        self.assertEqual(self.product.stock, Decimal("9.000"))
        commit.assert_called_once()
        release.assert_not_called()

    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    @patch("apps.mercado_pago.services.release_billing_reservation")
    @patch("apps.mercado_pago.services.commit_billing_reservation")
    def test_stale_failed_snapshot_cannot_beat_newer_paid_reconciliation(
        self, commit, release, reserve, client_class
    ):
        order = self._create_pending_order(reserve, client_class, key="versioned-race")
        order.reconcile_version = 2
        order.save(update_fields=["reconcile_version"])

        _finalize_order(
            order.uuid,
            MercadoPagoOrder.State.FAILED,
            expected_version=1,
        )
        _finalize_order(
            order.uuid,
            MercadoPagoOrder.State.PAID,
            expected_version=2,
        )

        order.refresh_from_db()
        order.sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.state, MercadoPagoOrder.State.PAID)
        self.assertEqual(order.sale.status, Sale.Status.COMPLETED)
        self.assertEqual(self.product.stock, Decimal("9.000"))
        commit.assert_called_once()
        release.assert_not_called()

    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    @patch("apps.mercado_pago.services.release_billing_reservation")
    @patch("apps.mercado_pago.services.commit_billing_reservation")
    def test_canonical_mismatches_keep_sales_pending_and_stock_reserved(
        self, commit, release, reserve, client_class
    ):
        mismatches = {
            "id": "ANOTHER-ORDER",
            "external_reference": "another-sale",
            "type": "qr",
            "total_amount": "1500.01",
            "collector_id": "ANOTHER-COLLECTOR",
            "currency": "USD",
            "live_mode": True,
        }

        for index, (field, invalid_value) in enumerate(mismatches.items(), start=1):
            with self.subTest(field=field):
                order = self._create_pending_order(
                    reserve, client_class, key=f"mismatch-{field}"
                )
                canonical = self._canonical(order, status="processed")
                canonical[field] = invalid_value
                remote = Mock()
                remote.get_order.return_value = canonical

                reconcile_order(order.uuid, client=remote)

                order.refresh_from_db()
                order.sale.refresh_from_db()
                self.product.refresh_from_db()
                self.assertEqual(order.state, MercadoPagoOrder.State.ERROR)
                self.assertEqual(order.last_error_code, "canonical_mismatch")
                self.assertEqual(order.sale.status, Sale.Status.PENDING)
                self.assertEqual(
                    self.product.stock, Decimal("10.000") - Decimal(index)
                )
        commit.assert_not_called()
        release.assert_not_called()

    @patch("apps.sales.views.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    @patch("apps.mercado_pago.services.commit_billing_reservation")
    def test_paid_sale_requests_one_idempotent_refund_and_restores_only_on_confirmation(
        self, commit, reserve, create_client_class, cancel_client_class
    ):
        order = self._create_pending_order(
            reserve, create_client_class, key="refund-key"
        )
        remote = Mock()
        paid = self._canonical(order, status="processed")
        paid.update(payment_status="processed", payment_status_detail="accredited")
        remote.get_order.return_value = paid
        reconcile_order(order.uuid, client=remote)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self._token(self.owner)}"
        )

        first = self.client.post(f"/api/v1/sales/{order.sale_id}/cancel/")
        repeated = self.client.post(f"/api/v1/sales/{order.sale_id}/cancel/")

        self.assertEqual(first.status_code, 202)
        self.assertEqual(repeated.status_code, 202)
        cancel_client_class.return_value.refund_order.assert_called_once()
        refund_call = cancel_client_class.return_value.refund_order.call_args
        self.assertLessEqual(len(refund_call.kwargs["idempotency_key"]), 160)
        order.refresh_from_db()
        order.sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.state, MercadoPagoOrder.State.REFUND_PENDING)
        self.assertEqual(order.sale.status, Sale.Status.COMPLETED)
        self.assertEqual(self.product.stock, Decimal("9.000"))

        refunded = self._canonical(order, status="refunded")
        remote.get_order.return_value = refunded
        reconcile_order(order.uuid, client=remote)
        reconcile_order(order.uuid, client=remote)

        order.refresh_from_db()
        order.sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.state, MercadoPagoOrder.State.REFUNDED)
        self.assertEqual(order.sale.status, Sale.Status.CANCELLED)
        self.assertEqual(self.product.stock, Decimal("10.000"))

    @patch("apps.sales.views.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    def test_pending_cancel_reports_terminal_intervention_without_restoring_stock(
        self, reserve, create_client_class, cancel_client_class
    ):
        order = self._create_pending_order(
            reserve, create_client_class, key="terminal-intervention"
        )
        cancel_client_class.return_value.cancel_order.side_effect = PlatformBillingError(
            "Terminal intervention required",
            status_code=409,
            response_data={
                "detail": {
                    "code": "point_action_required",
                    "message": "Use the Point terminal to cancel the order.",
                }
            },
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self._token(self.owner)}"
        )

        response = self.client.post(f"/api/v1/sales/{order.sale_id}/cancel/")

        order.refresh_from_db()
        order.sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "point_action_required")
        self.assertEqual(order.state, MercadoPagoOrder.State.ACTION_REQUIRED)
        cancel_key = order.cancel_idempotency_key
        self.assertTrue(cancel_key)
        self.assertEqual(order.sale.status, Sale.Status.PENDING)
        self.assertEqual(self.product.stock, Decimal("9.000"))

        repeated = self.client.post(f"/api/v1/sales/{order.sale_id}/cancel/")

        order.refresh_from_db()
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(repeated.data["code"], "point_action_required")
        self.assertEqual(order.state, MercadoPagoOrder.State.ACTION_REQUIRED)
        self.assertEqual(order.cancel_idempotency_key, cancel_key)
        cancel_client_class.return_value.cancel_order.assert_called_once()

        worker_client = Mock()
        worker_client.get_order.return_value = self._canonical(
            order, status="created"
        )
        MercadoPagoWorker(client=worker_client, batch_size=1)._process_order(order.uuid)

        order.refresh_from_db()
        self.assertEqual(order.state, MercadoPagoOrder.State.ACTION_REQUIRED)
        self.assertEqual(order.cancel_idempotency_key, cancel_key)
        worker_client.get_order.assert_called_once_with(
            order.tenant_id, order.external_order_id
        )
        worker_client.cancel_order.assert_not_called()

    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    def test_pending_payment_blocks_cashbox_close(self, reserve, client_class):
        self._create_pending_order(reserve, client_class, key="close-key")

        response = self.client.post(
            "/api/v1/cashboxes/close/", {"final_amount": "100.00"}, format="json"
        )

        self.assertEqual(response.status_code, 409)
        self.cashbox.refresh_from_db()
        self.assertEqual(self.cashbox.status, Cashbox.Status.OPEN)

    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    def test_pending_canonical_state_preserves_cancel_intent(self, reserve, client_class):
        order = self._create_pending_order(reserve, client_class, key="cancel-intent")
        order.cancel_idempotency_key = "cancel-key"
        order.state = MercadoPagoOrder.State.CANCEL_REQUESTED
        order.save(update_fields=["cancel_idempotency_key", "state"])
        remote = Mock()
        remote.get_order.return_value = self._canonical(order, status="created")

        reconcile_order(order.uuid, client=remote)

        order.refresh_from_db()
        self.assertEqual(order.state, MercadoPagoOrder.State.CANCEL_REQUESTED)
        self.assertEqual(order.cancel_idempotency_key, "cancel-key")

    @patch(
        "apps.mercado_pago.services.release_billing_reservation",
        side_effect=RuntimeError("platform unavailable"),
    )
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    def test_failed_local_persistence_leaves_durable_billing_release(
        self, reserve, _release
    ):
        reserve.return_value = {"allowed": True, "status": "active", "reservation_id": str(uuid.uuid4())}
        self.register.mercado_pago_external_pos_id = None
        self.register.save(update_fields=["mercado_pago_external_pos_id"])

        response = self.client.post(
            "/api/v1/sales/",
            self._sale_body("QR", "1500.00"),
            format="json",
            HTTP_X_IDEMPOTENCY_KEY="release-intent",
        )

        self.assertEqual(response.status_code, 400)
        task = MercadoPagoBillingRelease.objects.get()
        self.assertFalse(
            MercadoPagoOrder.objects.filter(
                billing_reservation_key=task.idempotency_key
            ).exists()
        )

        billing_client = Mock()
        billing_client.release_usage_reservation.return_value = {
            "allowed": True,
            "status": "released",
        }
        MercadoPagoWorker(client=billing_client, batch_size=1).run_once()
        billing_client.release_usage_reservation.assert_called_once_with(
            task.tenant_id,
            idempotency_key=task.idempotency_key,
        )
        self.assertFalse(MercadoPagoBillingRelease.objects.exists())

    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    @patch(
        "apps.mercado_pago.services.commit_billing_reservation",
        side_effect=BillingEnforcementError(
            {"code": "billing_service_unavailable", "detail": "temporary"},
            503,
        ),
    )
    def test_worker_retries_when_paid_transition_cannot_commit_billing(
        self, _commit, reserve, client_class
    ):
        order = self._create_pending_order(
            reserve, client_class, key="billing-commit-retry"
        )
        worker_client = Mock()
        canonical = self._canonical(order, status="processed")
        canonical.update(payment_status="processed", payment_status_detail="accredited")
        worker_client.get_order.return_value = canonical

        MercadoPagoWorker(client=worker_client, batch_size=1)._process_order(order.uuid)

        order.refresh_from_db()
        order.sale.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.state, MercadoPagoOrder.State.PENDING)
        self.assertEqual(order.sale.status, Sale.Status.PENDING)
        self.assertEqual(order.retry_count, 1)
        self.assertIsNotNone(order.next_retry_at)
        self.assertIsNone(order.locked_at)
        self.assertEqual(self.product.stock, Decimal("9.000"))

    @patch("apps.mercado_pago.views.PlatformMercadoPagoClient")
    def test_oauth_configuration_is_owner_only_and_uses_jwt_tenant(
        self, client_class
    ):
        client_class.return_value.start_oauth.return_value = {
            "authorization_url": "https://auth.example/authorize",
            "expires_at": "2026-09-07T12:00:00Z",
        }

        forbidden = self.client.post("/api/v1/mercado-pago/oauth/start/")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self._token(self.owner)}"
        )
        allowed = self.client.post("/api/v1/mercado-pago/oauth/start/")

        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(allowed.status_code, 200)
        client_class.return_value.start_oauth.assert_called_once_with(str(self.tenant.uuid))

    @patch("apps.mercado_pago.views.PlatformMercadoPagoClient")
    def test_cash_register_association_cannot_cross_tenant(self, client_class):
        other_tenant = Tenant.objects.create(uuid=uuid.uuid4(), name="Other tenant")
        other_register = CashRegister.objects.create(
            tenant_id=other_tenant.uuid,
            name="Other register",
        )
        client_class.return_value.list_terminals.return_value = {
            "results": [{"id": "POINT-OTHER"}]
        }
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self._token(self.owner)}"
        )

        response = self.client.put(
            f"/api/v1/mercado-pago/cash-registers/{other_register.uuid}/association/",
            {"terminal_id": "POINT-OTHER"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        other_register.refresh_from_db()
        self.assertIsNone(other_register.mercado_pago_terminal_id)

    @patch("apps.mercado_pago.views.PlatformMercadoPagoClient")
    def test_qr_association_rejects_mismatched_pair_and_persists_discovered_ids(
        self, client_class
    ):
        client_class.return_value.list_pos.return_value = {
            "results": [
                {"id": 10, "external_id": "POS-CANONICAL"},
                {"id": 20, "external_id": "POS-OTHER"},
            ]
        }
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {self._token(self.owner)}"
        )

        mismatch = self.client.put(
            f"/api/v1/mercado-pago/cash-registers/{self.register.uuid}/association/",
            {"pos_id": "10", "external_pos_id": "POS-OTHER"},
            format="json",
        )

        self.assertEqual(mismatch.status_code, 400)
        self.assertEqual(
            str(mismatch.data["detail"]),
            "POS does not belong to this tenant connection.",
        )
        self.register.refresh_from_db()
        self.assertEqual(self.register.mercado_pago_pos_id, "10")
        self.assertEqual(self.register.mercado_pago_external_pos_id, "POS-1")

        associated = self.client.put(
            f"/api/v1/mercado-pago/cash-registers/{self.register.uuid}/association/",
            {"pos_id": "10"},
            format="json",
        )

        self.assertEqual(associated.status_code, 200)
        self.register.refresh_from_db()
        self.assertEqual(self.register.mercado_pago_pos_id, "10")
        self.assertEqual(
            self.register.mercado_pago_external_pos_id, "POS-CANONICAL"
        )

    def test_mercado_pago_resources_are_unique_within_but_not_across_tenants(self):
        other_tenant = Tenant.objects.create(uuid=uuid.uuid4(), name="Other tenant")
        same_external_resources = CashRegister.objects.create(
            tenant_id=other_tenant.uuid,
            name="Other register",
            mercado_pago_terminal_id="POINT-1",
            mercado_pago_pos_id="10",
            mercado_pago_external_pos_id="POS-1",
        )

        self.assertEqual(same_external_resources.mercado_pago_terminal_id, "POINT-1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashRegister.objects.create(
                    tenant_id=self.tenant.uuid,
                    name="Duplicate local terminal",
                    mercado_pago_terminal_id="POINT-1",
                )

    @patch("apps.mercado_pago.services.PlatformMercadoPagoClient")
    @patch("apps.mercado_pago.services.reserve_billing_usage")
    def test_external_order_identity_is_globally_unique(
        self, reserve, client_class
    ):
        order = self._create_pending_order(
            reserve, client_class, key="global-external-order"
        )
        other_tenant = Tenant.objects.create(
            uuid=uuid.uuid4(), name="External identity tenant"
        )
        other_user = User.objects.create_user(
            tenant_id=other_tenant.uuid,
            username="external-identity-owner",
            email="external-identity@example.com",
            password="secret",
            role=User.Role.OWNER,
        )
        other_register = CashRegister.objects.create(
            tenant_id=other_tenant.uuid, name="External identity register"
        )
        other_cashbox = Cashbox.objects.create(
            tenant_id=other_tenant.uuid,
            register=other_register,
            opened_by=other_user,
            initial_amount=Decimal("0.00"),
        )
        second_sale = Sale.objects.create(
            tenant_id=other_tenant.uuid,
            user=other_user,
            cashbox=other_cashbox,
            total=Decimal("1500.00"),
            payment_method=Sale.PaymentMethod.POINT,
            payments=[{"method": "POINT", "amount": "1500.00"}],
            status=Sale.Status.PENDING,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MercadoPagoOrder.objects.create(
                    tenant_id=second_sale.tenant_id,
                    sale=second_sale,
                    amount=Decimal("1500.00"),
                    order_type=MercadoPagoOrder.Type.POINT,
                    external_order_id=order.external_order_id,
                    external_reference=str(second_sale.uuid),
                    frontend_idempotency_key="second-frontend-key",
                    request_fingerprint="f" * 64,
                    create_idempotency_key="second-create-key",
                    billing_reservation_key="second-billing-key",
                )

    def _create_pending_order(self, reserve, client_class, *, key):
        reserve.return_value = {"allowed": True, "reservation_id": str(uuid.uuid4())}
        client_class.return_value.create_order.return_value = {
            "id": f"ORDER-{key}",
            "status": "created",
            "collector_id": "COLLECTOR-1",
            "currency": "ARS",
            "live_mode": False,
            "total_amount": "1500.00",
        }
        response = self.client.post(
            "/api/v1/sales/",
            self._sale_body("POINT", "1500.00"),
            format="json",
            HTTP_X_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(response.status_code, 202)
        return MercadoPagoOrder.objects.select_related("sale").get(sale_id=response.data["uuid"])

    @staticmethod
    def _canonical(order, *, status):
        return {
            "id": order.external_order_id,
            "external_reference": order.external_reference,
            "type": order.order_type.lower(),
            "currency": order.currency,
            "total_amount": str(order.amount),
            "collector_id": order.collector_id,
            "live_mode": order.live_mode,
            "status": status,
        }

    def _sale_body(self, method, amount):
        return {
            "payments": [{"method": method, "amount": amount}],
            "items": [{"product_id": str(self.product.uuid), "quantity": "1.000"}],
        }

    @staticmethod
    def _token(user):
        access = RefreshToken.for_user(user).access_token
        access["tenant_id"] = str(user.tenant_id)
        access["role"] = user.role
        return str(access)


@override_settings(MERCADO_PAGO_WEBHOOK_SECRET="webhook-secret")
class MercadoPagoWebhookTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_invalid_signature_is_rejected(self):
        response = self.client.post(
            "/api/v1/webhooks/mercado-pago/orders/?data.id=ORDER-1",
            {"id": "notification-1", "type": "order", "action": "order.processed"},
            format="json",
            HTTP_X_REQUEST_ID="request-1",
            HTTP_X_SIGNATURE="ts=1,v1=invalid",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(MercadoPagoWebhookInbox.objects.count(), 0)

    @override_settings(MERCADO_PAGO_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS=300)
    def test_valid_but_stale_signature_is_rejected(self):
        timestamp = str(int(time.time()) - 301)
        response = self.client.post(
            "/api/v1/webhooks/mercado-pago/orders/?data.id=ORDER-STALE",
            {"id": "notification-stale", "type": "order"},
            format="json",
            HTTP_X_REQUEST_ID="request-stale",
            HTTP_X_SIGNATURE=self._signature(
                "request-stale", "ORDER-STALE", timestamp
            ),
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(MercadoPagoWebhookInbox.objects.count(), 0)

    def test_notification_id_deduplicates_retries_with_different_request_ids(self):
        body = {"id": "notification-1", "type": "order", "action": "order.processed"}
        for request_id in ("request-1", "request-2"):
            signature = self._signature(request_id, "ORDER-1", str(int(time.time())))
            response = self.client.post(
                "/api/v1/webhooks/mercado-pago/orders/?data.id=ORDER-1",
                body,
                format="json",
                HTTP_X_REQUEST_ID=request_id,
                HTTP_X_SIGNATURE=signature,
            )
            self.assertEqual(response.status_code, 200)

        self.assertEqual(MercadoPagoWebhookInbox.objects.count(), 1)

    def test_unknown_topic_is_durable_and_worker_marks_it_ignored(self):
        signature = self._signature("request-unknown", "RESOURCE-1", str(int(time.time())))
        response = self.client.post(
            "/api/v1/webhooks/mercado-pago/orders/?data.id=RESOURCE-1",
            {"id": "notification-unknown", "type": "payment", "action": "payment.updated"},
            format="json",
            HTTP_X_REQUEST_ID="request-unknown",
            HTTP_X_SIGNATURE=signature,
        )
        inbox = MercadoPagoWebhookInbox.objects.get()

        MercadoPagoWorker(client=Mock())._process_inbox(inbox.uuid)

        inbox.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(inbox.status, MercadoPagoWebhookInbox.Status.IGNORED)

    def test_known_notification_retries_when_remote_order_is_not_linked_yet(self):
        signature = self._signature("request-early", "ORDER-EARLY", str(int(time.time())))
        self.client.post(
            "/api/v1/webhooks/mercado-pago/orders/?data.id=ORDER-EARLY",
            {"id": "notification-early", "type": "order", "action": "order.processed"},
            format="json",
            HTTP_X_REQUEST_ID="request-early",
            HTTP_X_SIGNATURE=signature,
        )
        inbox = MercadoPagoWebhookInbox.objects.get()

        MercadoPagoWorker(client=Mock())._process_inbox(inbox.uuid)

        inbox.refresh_from_db()
        self.assertEqual(inbox.status, MercadoPagoWebhookInbox.Status.RETRYING)
        self.assertEqual(inbox.last_error_code, "order_not_linked")
        self.assertIsNotNone(inbox.next_attempt_at)

    @staticmethod
    def _signature(request_id, data_id, timestamp):
        manifest = f"id:{data_id};request-id:{request_id};ts:{timestamp};"
        digest = hmac.new(
            b"webhook-secret", manifest.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return f"ts={timestamp},v1={digest}"


class PlatformMercadoPagoClientTests(TestCase):
    def test_mutable_calls_forward_the_same_idempotency_header(self):
        client = PlatformMercadoPagoClient(
            base_url="http://platform.test", service_token="token", source="postas_api"
        )
        client._request = Mock(return_value={})

        client.create_order(uuid.uuid4(), {"type": "point"}, idempotency_key="same-key")
        self.assertEqual(
            client._request.call_args.kwargs["extra_headers"],
            {"X-Idempotency-Key": "same-key"},
        )
