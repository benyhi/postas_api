from django.urls import path

from apps.cashbox.views import CashRegisterDetailView, CashRegisterListCreateView


urlpatterns = [
    path("", CashRegisterListCreateView.as_view(), name="cash-register-list-create"),
    path("<uuid:uuid>/", CashRegisterDetailView.as_view(), name="cash-register-detail"),
]
