import csv

from django.http import HttpResponse
from rest_framework import generics, filters, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample, OpenApiParameter

from apps.products.importer import (
    ProductImportFormatError,
    ProductImportService,
    build_failed_import_payload,
)
from apps.products.models import Category, Product
from apps.products.serializers import CategorySerializer, ProductImportUploadSerializer, ProductSerializer
from core.permissions.roles import IsAdminOrOwner, IsAdminOrOwnerOrReadOnly
from core.utils.audit import log_action


class ProductPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 5000


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
    pagination_class = ProductPagination

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


@extend_schema(
    summary="Importar productos",
    description=(
        "Recibe un archivo CSV, XLSX o XLS en multipart/form-data y crea o actualiza "
        "productos del tenant. Columnas requeridas: name/nombre y price/precio. "
        "Columnas opcionales: description, cost, unit, stock, min_stock, barcode, "
        "image_url, category y category_id. Si el barcode o el name coinciden con "
        "un producto activo del tenant, se actualiza ese producto y se reporta en matches."
    ),
    tags=["Products"],
    request=ProductImportUploadSerializer,
    responses={
        200: OpenApiTypes.OBJECT,
        400: OpenApiTypes.OBJECT,
        403: OpenApiTypes.OBJECT,
    },
    examples=[
        OpenApiExample(
            "Respuesta OK",
            value={
                "result": "OK",
                "summary": {
                    "total_rows": 2,
                    "created": 1,
                    "updated": 1,
                    "failed": 0,
                    "matches": 1,
                    "elapsed_ms": 42,
                    "eta_ms": 0,
                },
                "items_loaded": [],
                "matches": [],
                "errors": [],
            },
            response_only=True,
        ),
    ],
)
class ProductImportView(APIView):
    permission_classes = [IsAdminOrOwner]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = ProductImportUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = ProductImportService()
        try:
            result = service.import_upload(
                tenant_id=request.tenant_id,
                upload=serializer.validated_data["file"],
            )
        except ProductImportFormatError as exc:
            return Response(
                build_failed_import_payload(exc.message, exc.code, exc.errors),
                status=status.HTTP_400_BAD_REQUEST,
            )

        items_loaded = []
        for item in result["items"]:
            product_data = ProductSerializer(item["product"], context={"request": request}).data
            items_loaded.append({
                "row": item["row"],
                "action": item["action"],
                "match_type": item["match_type"],
                "product": product_data,
            })

        payload = {
            "result": result["result"],
            "summary": result["summary"],
            "items_loaded": items_loaded,
            "matches": result["matches"],
            "errors": result["errors"],
        }
        response_status = status.HTTP_400_BAD_REQUEST if result["result"] == "FAILED" else status.HTTP_200_OK
        return Response(payload, status=response_status)


@extend_schema(
    summary="Exportar productos a CSV",
    description=(
        "Descarga todos los productos activos del tenant como un archivo CSV compatible con el endpoint de importación. "
        "Incluye BOM UTF-8 para compatibilidad con Excel."
    ),
    tags=["Products"],
    responses={(200, "text/csv"): OpenApiTypes.BINARY},
)
class ProductExportView(APIView):
    permission_classes = [IsAdminOrOwner]

    def get(self, request):
        products = (
            Product.objects.filter(tenant_id=request.tenant_id)
            .select_related("category")
            .order_by("name")
        )

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="inventario.csv"'
        response.write("﻿")  # BOM for Excel UTF-8 compatibility

        writer = csv.writer(response)
        writer.writerow([
            "nombre", "descripcion", "precio", "costo",
            "unidad", "stock", "stock_minimo",
            "codigo_barras", "imagen", "categoria",
        ])
        for p in products:
            writer.writerow([
                p.name,
                p.description,
                str(p.price),
                str(p.cost),
                p.unit,
                str(p.stock),
                str(p.min_stock),
                p.barcode,
                p.image_url,
                p.category.name if p.category else "",
            ])

        return response


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
