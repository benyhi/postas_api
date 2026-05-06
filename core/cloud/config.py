from django.conf import settings


def get_r2_settings() -> dict:
    return {
        "bucket_name": getattr(settings, "R2_BUCKET_NAME", None),
        "access_key": getattr(settings, "R2_ACCESS_KEY_ID", None),
        "secret_key": getattr(settings, "R2_SECRET_ACCESS_KEY", None),
        "region_name": getattr(settings, "R2_REGION", "auto"),
        "endpoint_url": getattr(settings, "R2_ENDPOINT_URL", None),
        "public_url": getattr(settings, "R2_PUBLIC_URL", None),
        "allowed_extensions": getattr(settings, "R2_ALLOWED_EXTENSIONS", (".jpg", ".jpeg", ".png", ".webp")),
        "max_size": getattr(settings, "R2_MAX_IMAGE_SIZE", 5 * 1024 * 1024),
    }
