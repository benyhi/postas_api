from django.urls import path

from apps.sales.views import (
    SaleListCreateView,
    SaleDetailView,
    SaleCancelView,
)

urlpatterns = [
    path("", SaleListCreateView.as_view(), name="sale-list-create"),
    path("<uuid:uuid>/", SaleDetailView.as_view(), name="sale-detail"),
    path("<uuid:uuid>/cancel/", SaleCancelView.as_view(), name="sale-cancel"),
]
