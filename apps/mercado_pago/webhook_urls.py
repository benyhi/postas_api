from django.urls import path

from apps.mercado_pago.webhooks import MercadoPagoOrdersWebhookView


urlpatterns = [
    path("orders/", MercadoPagoOrdersWebhookView.as_view(), name="mp-orders-webhook"),
]
