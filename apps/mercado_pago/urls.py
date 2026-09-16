from django.urls import path

from apps.mercado_pago.views import (
    CashRegisterAssociationView, ConnectionView, OAuthStartView, PosView, TerminalsView,
)


urlpatterns = [
    path("oauth/start/", OAuthStartView.as_view(), name="mp-oauth-start"),
    path("connection/", ConnectionView.as_view(), name="mp-connection"),
    path("terminals/", TerminalsView.as_view(), name="mp-terminals"),
    path("pos/", PosView.as_view(), name="mp-pos"),
    path("cash-registers/<uuid:uuid>/association/", CashRegisterAssociationView.as_view(), name="mp-cash-register-association"),
]
