from django.urls import path

from apps.cashbox.views import (
    CashboxOpenView,
    CashboxCloseView,
    CashboxCurrentView,
    CashboxListView,
    CashboxDetailView,
)

urlpatterns = [
    path("open/", CashboxOpenView.as_view(), name="cashbox-open"),
    path("close/", CashboxCloseView.as_view(), name="cashbox-close"),
    path("current/", CashboxCurrentView.as_view(), name="cashbox-current"),
    path("", CashboxListView.as_view(), name="cashbox-list"),
    path("<uuid:uuid>/", CashboxDetailView.as_view(), name="cashbox-detail"),
]
