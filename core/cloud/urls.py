from django.urls import path

from .views import BucketHealthView, ImageDetailView, ImageListUploadView, PublicImageView

cloud_urlpatterns = [
    # Autenticados (cualquier rol)
    path("images/", ImageListUploadView.as_view(), name="cloud-images"),
    path("images/<path:key>/", ImageDetailView.as_view(), name="cloud-image-detail"),

    # Público (sin autenticación, solo lectura)
    path("public/images/", PublicImageView.as_view(), name="cloud-public-images"),
    path("public/images/<path:key>/", PublicImageView.as_view(), name="cloud-public-image-detail"),

    # Admin
    path("health/", BucketHealthView.as_view(), name="cloud-health"),
]
