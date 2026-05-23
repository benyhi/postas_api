from django.urls import path

from .views import (
    DocumentExtractionDetailView,
    DocumentExtractionListCreateView,
    DocumentExtractionTestFormView,
)


urlpatterns = [
    path("test-form/", DocumentExtractionTestFormView.as_view(), name="document-extraction-test-form"),
    path("", DocumentExtractionListCreateView.as_view(), name="document-extraction-list-create"),
    path("<uuid:uuid>/", DocumentExtractionDetailView.as_view(), name="document-extraction-detail"),
]
