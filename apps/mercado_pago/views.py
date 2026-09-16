from django.db import IntegrityError, transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.cashbox.models import CashRegister
from apps.cashbox.serializers import CashRegisterSerializer
from apps.mercado_pago.client import PlatformMercadoPagoClient
from apps.mercado_pago.models import MercadoPagoOrder
from apps.mercado_pago.serializers import (
    CashRegisterAssociationSerializer,
    ConnectionStatusSerializer,
    OAuthAuthorizationResponseSerializer,
    ResourceDiscoverySerializer,
)
from apps.platform_billing.client import PlatformBillingError
from apps.tenants.models import Tenant
from core.permissions.roles import IsOwner
from core.utils.audit import log_action


def _platform_error(exc):
    code = exc.status_code if 400 <= exc.status_code < 600 else 503
    detail = exc.response_data.get("detail")
    nested = detail if isinstance(detail, dict) else {}
    payload = {
        "detail": nested.get("message") or exc.message,
        "code": nested.get("code") or exc.response_data.get("code", "mercado_pago_service_error"),
    }
    return Response(payload, status=code)


class OAuthStartView(APIView):
    permission_classes = [IsOwner]

    @extend_schema(
        tags=["Mercado Pago"],
        request=None,
        responses={200: OAuthAuthorizationResponseSerializer},
        summary="Iniciar OAuth de Mercado Pago",
    )
    def post(self, request):
        try:
            data = PlatformMercadoPagoClient().start_oauth(request.tenant_id)
        except PlatformBillingError as exc:
            return _platform_error(exc)
        return Response(data)


class ConnectionView(APIView):
    permission_classes = [IsOwner]

    @extend_schema(
        tags=["Mercado Pago"],
        responses={200: ConnectionStatusSerializer},
        summary="Consultar conexion Mercado Pago",
    )
    def get(self, request):
        try:
            return Response(PlatformMercadoPagoClient().get_connection(request.tenant_id))
        except PlatformBillingError as exc:
            return _platform_error(exc)

    @extend_schema(
        tags=["Mercado Pago"],
        responses={200: ConnectionStatusSerializer},
        summary="Desvincular Mercado Pago",
    )
    def delete(self, request):
        with transaction.atomic():
            Tenant.objects.select_for_update().get(uuid=request.tenant_id)
            if MercadoPagoOrder.objects.filter(
                tenant_id=request.tenant_id,
                state__in=MercadoPagoOrder.ACTIVE_STATES,
            ).exists():
                return Response(
                    {"detail": "There are pending Mercado Pago operations."},
                    status=status.HTTP_409_CONFLICT,
                )
            try:
                data = PlatformMercadoPagoClient().delete_connection(request.tenant_id)
            except PlatformBillingError as exc:
                return _platform_error(exc)
            CashRegister.objects.filter(tenant_id=request.tenant_id).update(
                mercado_pago_terminal_id=None,
                mercado_pago_pos_id=None,
                mercado_pago_external_pos_id=None,
            )
        return Response(data)


class TerminalsView(APIView):
    permission_classes = [IsOwner]

    @extend_schema(
        tags=["Mercado Pago"],
        responses={200: ResourceDiscoverySerializer},
        summary="Descubrir terminales Point",
    )
    def get(self, request):
        try:
            return Response(PlatformMercadoPagoClient().list_terminals(request.tenant_id))
        except PlatformBillingError as exc:
            return _platform_error(exc)


class PosView(APIView):
    permission_classes = [IsOwner]

    @extend_schema(
        tags=["Mercado Pago"],
        responses={200: ResourceDiscoverySerializer},
        summary="Descubrir POS para QR dinamico",
    )
    def get(self, request):
        try:
            return Response(PlatformMercadoPagoClient().list_pos(request.tenant_id))
        except PlatformBillingError as exc:
            return _platform_error(exc)


class CashRegisterAssociationView(APIView):
    permission_classes = [IsOwner]

    @extend_schema(
        tags=["Mercado Pago"],
        request=CashRegisterAssociationSerializer,
        responses={200: CashRegisterSerializer},
        summary="Asociar recursos Mercado Pago a una caja",
    )
    def put(self, request, uuid):
        serializer = CashRegisterAssociationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        client = PlatformMercadoPagoClient()
        try:
            terminal_payload = client.list_terminals(request.tenant_id) if serializer.validated_data.get("terminal_id") else {}
            pos_payload = client.list_pos(request.tenant_id) if (
                serializer.validated_data.get("pos_id") or serializer.validated_data.get("external_pos_id")
            ) else {}
        except PlatformBillingError as exc:
            return _platform_error(exc)

        terminals = _resource_items(terminal_payload, "terminals")
        poses = _resource_items(pos_payload, "pos")
        terminal_id = serializer.validated_data.get("terminal_id")
        pos_id = serializer.validated_data.get("pos_id")
        external_pos_id = serializer.validated_data.get("external_pos_id")
        if terminal_id and not _contains_resource(terminals, terminal_id, "id", "terminal_id"):
            return Response({"detail": "Terminal does not belong to this tenant connection."}, status=400)
        selected_pos = _find_resource(poses, pos_id, external_pos_id)
        if (pos_id or external_pos_id) and selected_pos is None:
            return Response({"detail": "POS does not belong to this tenant connection."}, status=400)
        selected_external_pos_id = (
            str(selected_pos.get("external_id") or selected_pos.get("external_pos_id") or "")
            if selected_pos
            else ""
        )
        if (pos_id or external_pos_id) and not selected_external_pos_id:
            return Response(
                {"detail": "The selected POS has no external_pos_id required for dynamic QR."},
                status=400,
            )

        try:
            with transaction.atomic():
                Tenant.objects.select_for_update().get(uuid=request.tenant_id)
                register = CashRegister.objects.select_for_update().get(uuid=uuid, tenant_id=request.tenant_id)
                register.mercado_pago_terminal_id = terminal_id
                register.mercado_pago_pos_id = (
                    str(selected_pos.get("id")) if selected_pos and selected_pos.get("id") is not None else None
                )
                register.mercado_pago_external_pos_id = selected_external_pos_id or None
                register.save(update_fields=["mercado_pago_terminal_id", "mercado_pago_pos_id", "mercado_pago_external_pos_id", "updated_at"])
        except CashRegister.DoesNotExist:
            return Response({"detail": "Cash register not found."}, status=404)
        except IntegrityError:
            return Response({"detail": "Mercado Pago resource is already associated with another cash register."}, status=409)
        log_action(request, "UPDATE", "CASH_REGISTER", register.uuid, {"action": "MP_ASSOCIATE"})
        return Response(CashRegisterSerializer(register, context={"request": request}).data)

    @extend_schema(
        tags=["Mercado Pago"],
        responses={204: None},
        summary="Desasociar recursos Mercado Pago de una caja",
    )
    def delete(self, request, uuid):
        with transaction.atomic():
            Tenant.objects.select_for_update().get(uuid=request.tenant_id)
            try:
                register = CashRegister.objects.select_for_update().get(uuid=uuid, tenant_id=request.tenant_id)
            except CashRegister.DoesNotExist:
                return Response({"detail": "Cash register not found."}, status=404)
            if MercadoPagoOrder.objects.filter(
                sale__cashbox__register=register, state__in=MercadoPagoOrder.ACTIVE_STATES,
            ).exists():
                return Response({"detail": "There are pending Mercado Pago operations for this cash register."}, status=409)
            register.mercado_pago_terminal_id = None
            register.mercado_pago_pos_id = None
            register.mercado_pago_external_pos_id = None
            register.save(update_fields=["mercado_pago_terminal_id", "mercado_pago_pos_id", "mercado_pago_external_pos_id", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


def _resource_items(payload, key):
    value = payload.get(key, payload.get("items", payload.get("results", [])))
    return value if isinstance(value, list) else []


def _contains_resource(items, value, *keys):
    return any(any(str(item.get(key)) == str(value) for key in keys) for item in items if isinstance(item, dict))


def _find_resource(items, pos_id, external_pos_id):
    for item in items:
        if not isinstance(item, dict):
            continue
        item_pos_id = item.get("id")
        item_external_id = item.get("external_id") or item.get("external_pos_id")
        if pos_id and str(item_pos_id) != str(pos_id):
            continue
        if external_pos_id and str(item_external_id) != str(external_pos_id):
            continue
        if pos_id or external_pos_id:
            return item
    return None
