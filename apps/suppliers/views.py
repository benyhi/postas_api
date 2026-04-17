from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter

from apps.suppliers.models import Supplier, ProductSupplier
from apps.suppliers.serializers import (
    SupplierSerializer,
    ProductSupplierSerializer,
    SwitchSupplierSerializer,
)
from apps.suppliers.services import switch_supplier
from core.permissions.roles import IsAdminOrOwner
from core.utils.audit import log_action


# ── Suppliers ─────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(summary="Listar proveedores", tags=["Suppliers"]),
    create=extend_schema(summary="Crear proveedor", tags=["Suppliers"]),
)
class SupplierListCreateView(generics.ListCreateAPIView):
    serializer_class = SupplierSerializer
    permission_classes = [IsAdminOrOwner]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Supplier.objects.none()
        return Supplier.objects.filter(tenant_id=self.request.tenant_id)

    def perform_create(self, serializer):
        supplier = serializer.save()
        log_action(self.request, "CREATE", "SUPPLIER", supplier.uuid, {"name": supplier.name})


@extend_schema_view(
    retrieve=extend_schema(summary="Obtener proveedor", tags=["Suppliers"]),
    update=extend_schema(summary="Actualizar proveedor (PUT)", tags=["Suppliers"]),
    partial_update=extend_schema(summary="Actualizar proveedor (PATCH)", tags=["Suppliers"]),
    destroy=extend_schema(summary="Eliminar proveedor (soft delete)", tags=["Suppliers"]),
)
class SupplierDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SupplierSerializer
    permission_classes = [IsAdminOrOwner]
    lookup_field = "uuid"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Supplier.objects.none()
        return Supplier.objects.filter(tenant_id=self.request.tenant_id)

    def perform_update(self, serializer):
        supplier = serializer.save()
        log_action(self.request, "UPDATE", "SUPPLIER", supplier.uuid, {"name": supplier.name})

    def perform_destroy(self, instance):
        instance.active = False
        instance.save(update_fields=["active"])
        log_action(self.request, "DELETE", "SUPPLIER", instance.uuid, {"name": instance.name})


# ── ProductSupplier ───────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(
        summary="Listar relaciones producto-proveedor",
        tags=["Suppliers"],
        parameters=[
            OpenApiParameter(name="product", description="Filtrar por UUID de producto", type=str, required=False),
            OpenApiParameter(name="is_current", description="Filtrar solo activos (true/false)", type=str, required=False),
        ],
    ),
    create=extend_schema(summary="Asignar proveedor a producto", tags=["Suppliers"]),
)
class ProductSupplierListCreateView(generics.ListCreateAPIView):
    serializer_class = ProductSupplierSerializer
    permission_classes = [IsAdminOrOwner]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ProductSupplier.objects.none()
        qs = ProductSupplier.objects.filter(
            product__tenant_id=self.request.tenant_id
        ).select_related("supplier", "product")
        product_uuid = self.request.query_params.get("product")
        if product_uuid:
            qs = qs.filter(product__uuid=product_uuid)
        is_current = self.request.query_params.get("is_current")
        if is_current is not None:
            qs = qs.filter(is_current=is_current.lower() == "true")
        return qs

    def perform_create(self, serializer):
        ps = serializer.save()
        log_action(self.request, "CREATE", "PRODUCT_SUPPLIER", ps.uuid, {
            "product": str(ps.product_id),
            "supplier": str(ps.supplier_id),
        })


@extend_schema_view(
    retrieve=extend_schema(summary="Obtener relacion producto-proveedor", tags=["Suppliers"]),
    partial_update=extend_schema(summary="Actualizar precio de relacion (PATCH)", tags=["Suppliers"]),
    destroy=extend_schema(summary="Desactivar relacion producto-proveedor", tags=["Suppliers"]),
)
class ProductSupplierDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProductSupplierSerializer
    permission_classes = [IsAdminOrOwner]
    lookup_field = "uuid"
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ProductSupplier.objects.none()
        return ProductSupplier.objects.filter(
            product__tenant_id=self.request.tenant_id
        ).select_related("supplier", "product")

    def perform_destroy(self, instance):
        from datetime import date
        instance.is_current = False
        instance.until = date.today()
        instance.save(update_fields=["is_current", "until"])
        log_action(self.request, "DELETE", "PRODUCT_SUPPLIER", instance.uuid, {
            "product": str(instance.product_id),
            "supplier": str(instance.supplier_id),
        })


# ── Switch supplier ───────────────────────────────────────────

@extend_schema(
    summary="Cambiar proveedor activo de un producto",
    description="Desactiva todos los proveedores activos del producto y asigna el nuevo.",
    tags=["Suppliers"],
    request=SwitchSupplierSerializer,
    responses={201: ProductSupplierSerializer},
)
class SwitchSupplierView(APIView):
    permission_classes = [IsAdminOrOwner]

    def post(self, request):
        serializer = SwitchSupplierSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        from apps.products.models import Product
        product = Product.objects.get(
            uuid=serializer.validated_data["product_uuid"],
            tenant_id=request.tenant_id,
        )
        supplier = Supplier.objects.get(
            uuid=serializer.validated_data["supplier_uuid"],
            tenant_id=request.tenant_id,
        )
        price = serializer.validated_data.get("price")

        ps = switch_supplier(product, supplier, price)
        log_action(request, "UPDATE", "PRODUCT_SUPPLIER", ps.uuid, {
            "product": str(product.uuid),
            "supplier": str(supplier.uuid),
            "action": "switch",
        })

        output = ProductSupplierSerializer(ps, context={"request": request})
        return Response(output.data, status=status.HTTP_201_CREATED)
