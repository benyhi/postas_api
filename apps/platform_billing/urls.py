from django.urls import path

from .views import CurrentTenantBillingStatusView


urlpatterns = [
    path("current-plan/", CurrentTenantBillingStatusView.as_view(), name="billing-current-plan"),
]
