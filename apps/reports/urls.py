from django.urls import path

from apps.reports.views import (
    DailySalesReportView,
    SalesByPaymentReportView,
    TopProductsReportView,
    CashboxSummaryReportView,
    SalesByDateView,
)

urlpatterns = [
    path("sales/daily/", DailySalesReportView.as_view(), name="report-daily-sales"),
    path("sales/by-date/", SalesByDateView.as_view(), name="report-sales-by-date"),
    path("sales/by-payment/", SalesByPaymentReportView.as_view(), name="report-by-payment"),
    path("products/top/", TopProductsReportView.as_view(), name="report-top-products"),
    path("cashbox/summary/", CashboxSummaryReportView.as_view(), name="report-cashbox-summary"),
]
