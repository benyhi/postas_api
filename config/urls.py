"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

from apps.users.urls import auth_urlpatterns, users_urlpatterns
from apps.products.urls import products_urlpatterns, categories_urlpatterns
from apps.suppliers.urls import suppliers_urlpatterns, product_suppliers_urlpatterns
from core.cloud.urls import cloud_urlpatterns


def healthz(_request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path('healthz/', healthz, name='healthz'),
    path('admin/', admin.site.urls),

    # Docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Auth
    path('api/v1/auth/', include(auth_urlpatterns)),

    # Users
    path('api/v1/users/', include(users_urlpatterns)),

    # Products & Categories
    path('api/v1/products/', include(products_urlpatterns)),
    path('api/v1/categories/', include(categories_urlpatterns)),

    # Sales
    path('api/v1/sales/', include('apps.sales.urls')),

    # Cashbox
    path('api/v1/cashboxes/', include('apps.cashbox.urls')),

    # Reports
    path('api/v1/reports/', include('apps.reports.urls')),

    # Audit
    path('api/v1/audit/', include('apps.audit.urls')),

    # Suppliers
    path('api/v1/suppliers/', include(suppliers_urlpatterns)),
    path('api/v1/product-suppliers/', include(product_suppliers_urlpatterns)),

    # Tenant configuration
    path('api/v1/tenant/', include('apps.tenants.urls')),

    # Billing / plans
    path('api/v1/billing/', include('apps.platform_billing.urls')),

    # Cloud / Storage
    path('api/v1/cloud/', include(cloud_urlpatterns)),

    # Document extractor
    path('api/v1/document-extractions/', include('apps.document_extractor.urls')),
]
