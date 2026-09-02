from django.urls import path

from apps.arca.views import (
    ArcaConfigurationView,
    ArcaExplicitInvoiceCreateView,
    ArcaFiscalReferenceView,
    ArcaInvoiceByExternalIdView,
    ArcaInvoiceCreateView,
    ArcaLastVoucherView,
    ArcaSalesPointDiscoveryView,
)


urlpatterns = [
    path("configuration/", ArcaConfigurationView.as_view(), name="arca-configuration"),
    path(
        "configuration/sales-points/",
        ArcaSalesPointDiscoveryView.as_view(),
        name="arca-sales-point-discovery",
    ),
    path("invoices/", ArcaInvoiceCreateView.as_view(), name="arca-invoice-create"),
    path("invoices/explicit/", ArcaExplicitInvoiceCreateView.as_view(), name="arca-invoice-explicit"),
    path("invoices/by-external-id/<str:external_id>/", ArcaInvoiceByExternalIdView.as_view(), name="arca-invoice-external"),
    path("invoices/fiscal/", ArcaFiscalReferenceView.as_view(), name="arca-invoice-fiscal"),
    path("invoices/last-voucher/", ArcaLastVoucherView.as_view(), name="arca-last-voucher"),
]
