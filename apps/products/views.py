from rest_framework import generics, filters
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiParameter

from apps.products.models import Category, Product
from apps.products.serializers import CategorySerializer, ProductSerializer
from core.permissions.roles import IsAdminOrOwner, IsAdminOrOwnerOrReadOnly
from core.utils.audit import log_action


# ── Categories ───────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(
        summary="Listar categorias",
        description="Devuelve la lista paginada de categorias del tenant. Cualquier usuario autenticado puede leer.",
        tags=["Categories"],
    ),
    create=extend_schema(
        summary="Crear categoria",
        description="Crea una nueva categoria. Solo ADMIN u OWNER.",
        tags=["Categories"],
        examples=[
            OpenApiExample(
                "Crear categoria",
                value={"name": "Bebidas"},
                request_only=True,
            ),
        ],
    ),
)
class CategoryListCreateView(generics.ListCreateAPIView):
    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrOwnerOrReadOnly]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Category.objects.none()
        return Category.objects.filter(tenant_id=self.request.tenant_id)

    def perform_create(self, serializer):
        cat = serializer.save()
        log_action(self.request, "CREATE", "CATEGORY", cat.uuid, {"name": cat.name})


@extend_schema_view(
    retrieve=extend_schema(summary="Obtener categoria", tags=["Categories"]),
    update=extend_schema(summary="Actualizar categoria (PUT)", tags=["Categories"]),
    partial_update=extend_schema(summary="Actualizar categoria (PATCH)", tags=["Categories"]),
    destroy=extend_schema(summary="Eliminar categoria (soft delete)", tags=["Categories"]),
)
class CategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrOwnerOrReadOnly]
    lookup_field = "uuid"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Category.objects.none()
        return Category.objects.filter(tenant_id=self.request.tenant_id)

    def perform_update(self, serializer):
        cat = serializer.save()
        log_action(self.request, "UPDATE", "CATEGORY", cat.uuid, {"name": cat.name})

    def perform_destroy(self, instance):
        instance.active = False
        instance.save(update_fields=["active"])
        log_action(self.request, "DELETE", "CATEGORY", instance.uuid, {"name": instance.name})


# ── Products ─────────────────────────────────────────────────

@extend_schema_view(
    list=extend_schema(
        summary="Listar productos",
        description=(
            "Lista paginada de productos. Cualquier usuario autenticado puede leer. "
            "Soporta filtros por category_id y low_stock."
        ),
        tags=["Products"],
        parameters=[
            OpenApiParameter(name="category_id", description="Filtrar por UUID de categoria", type=str, required=False),
            OpenApiParameter(name="low_stock", description="Si es 'true', muestra solo productos con stock < min_stock", type=str, required=False, enum=["true", "false"]),
        ],
    ),
    create=extend_schema(
        summary="Crear producto",
        description="Crea un nuevo producto. Solo ADMIN u OWNER.",
        tags=["Products"],
        examples=[
            OpenApiExample(
                "Crear producto",
                value={"name": "Coca Cola 500ml", "price": "1500.00", "cost": "900.00", "stock": "50.000", "min_stock": "10.000", "unit": "UNIT", "barcode": "7790895000089", "category_id": "uuid-de-la-categoria"},
                request_only=True,
            ),
        ],
    ),
)
class ProductListCreateView(generics.ListCreateAPIView):
    serializer_class = ProductSerializer
    permission_classes = [IsAdminOrOwnerOrReadOnly]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = {"category": ["exact"]}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Product.objects.none()
        qs = Product.objects.filter(tenant_id=self.request.tenant_id)
        if self.request.query_params.get("low_stock") == "true":
            from django.db.models import F
            qs = qs.filter(stock__lt=F("min_stock"))
        category_id = self.request.query_params.get("category_id")
        if category_id:
            qs = qs.filter(category_id=category_id)
        return qs

    def perform_create(self, serializer):
        product = serializer.save()
        log_action(self.request, "CREATE", "PRODUCT", product.uuid, {
            "name": product.name, "price": str(product.price),
        })


@extend_schema_view(
    retrieve=extend_schema(summary="Obtener producto", tags=["Products"]),
    update=extend_schema(summary="Actualizar producto (PUT)", tags=["Products"]),
    partial_update=extend_schema(summary="Actualizar producto (PATCH)", tags=["Products"]),
    destroy=extend_schema(summary="Eliminar producto (soft delete)", tags=["Products"]),
)
class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProductSerializer
    permission_classes = [IsAdminOrOwnerOrReadOnly]
    lookup_field = "uuid"

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Product.objects.none()
        return Product.objects.filter(tenant_id=self.request.tenant_id)

    def perform_update(self, serializer):
        product = serializer.save()
        log_action(self.request, "UPDATE", "PRODUCT", product.uuid, {
            "name": product.name, "price": str(product.price),
        })

    def perform_destroy(self, instance):
        instance.active = False
        instance.save(update_fields=["active"])
        log_action(self.request, "DELETE", "PRODUCT", instance.uuid, {"name": instance.name})


@extend_schema(
    summary="Buscar productos",
    description="Busca productos por nombre o codigo de barras. Parametro: ?q=texto",
    tags=["Products"],
    parameters=[
        OpenApiParameter(name="q", description="Texto a buscar en nombre o barcode", type=str, required=False),
    ],
)
class ProductSearchView(generics.ListAPIView):
    serializer_class = ProductSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Product.objects.none()
        qs = Product.objects.filter(tenant_id=self.request.tenant_id)
        q = self.request.query_params.get("q", "").strip()
        if q:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=q) | Q(barcode__icontains=q))
        return qs
