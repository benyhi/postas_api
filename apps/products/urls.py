from django.urls import path

from apps.products.views import (
    CategoryListCreateView,
    CategoryDetailView,
    ProductListCreateView,
    ProductDetailView,
    ProductSearchView,
)

categories_urlpatterns = [
    path("", CategoryListCreateView.as_view(), name="category-list-create"),
    path("<uuid:uuid>/", CategoryDetailView.as_view(), name="category-detail"),
]

products_urlpatterns = [
    path("", ProductListCreateView.as_view(), name="product-list-create"),
    path("search/", ProductSearchView.as_view(), name="product-search"),
    path("<uuid:uuid>/", ProductDetailView.as_view(), name="product-detail"),
]
