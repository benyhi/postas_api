from django.urls import path

from apps.suppliers.views import (
    SupplierListCreateView,
    SupplierDetailView,
    ProductSupplierListCreateView,
    ProductSupplierDetailView,
    SwitchSupplierView,
)

suppliers_urlpatterns = [
    path("", SupplierListCreateView.as_view(), name="supplier-list-create"),
    path("<uuid:uuid>/", SupplierDetailView.as_view(), name="supplier-detail"),
]

product_suppliers_urlpatterns = [
    path("", ProductSupplierListCreateView.as_view(), name="product-supplier-list-create"),
    path("switch/", SwitchSupplierView.as_view(), name="product-supplier-switch"),
    path("<uuid:uuid>/", ProductSupplierDetailView.as_view(), name="product-supplier-detail"),
]
