import logging
import os
import re
from datetime import datetime
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import get_r2_settings


def _secure_filename(filename: str) -> str:
    filename = os.path.basename(filename)
    filename = re.sub(r"[^\w\s\-.]", "", filename)
    filename = re.sub(r"\s+", "_", filename).strip("._")
    return filename or "file"


class ImageService:
    def __init__(self):
        cfg = get_r2_settings()

        self.bucket_name = cfg["bucket_name"]
        self.public_url = cfg["public_url"]
        self.endpoint_url = cfg["endpoint_url"]
        self.region_name = cfg["region_name"]
        self.allowed_extensions = cfg["allowed_extensions"]
        self.max_size = cfg["max_size"]
        self.logger = logging.getLogger(__name__)

        if not all([self.bucket_name, cfg["access_key"], cfg["secret_key"]]):
            raise ValueError("Faltan credenciales R2 en settings (R2_BUCKET_NAME, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY)")

        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=cfg["access_key"],
            aws_secret_access_key=cfg["secret_key"],
            region_name=None if self.region_name == "auto" else self.region_name,
            endpoint_url=self.endpoint_url,
            config=Config(signature_version="s3v4"),
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    def _build_key(self, original_filename: str, folder: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = _secure_filename(original_filename)
        name, ext = os.path.splitext(safe)
        return f"{folder.strip('/')}/{timestamp}_{name}{ext}"

    def _public_url(self, key: str) -> str:
        if self.public_url:
            return f"{self.public_url.rstrip('/')}/{key}"
        if self.endpoint_url:
            return f"{self.endpoint_url}/{self.bucket_name}/{key}"
        return f"https://{self.bucket_name}.s3.{self.region_name}.amazonaws.com/{key}"

    def _content_type(self, ext: str) -> str:
        mapping = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        return mapping.get(ext.lower(), "application/octet-stream")

    # ── public API ────────────────────────────────────────────────────────────

    def upload(self, file_obj, filename: str, folder: str = "images") -> dict[str, Any]:
        ext = os.path.splitext(filename)[1].lower()
        if ext not in self.allowed_extensions:
            return {"success": False, "error": f"Extensión no permitida. Permitidas: {', '.join(self.allowed_extensions)}"}

        key = self._build_key(filename, folder)
        try:
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=file_obj,
                ContentType=self._content_type(ext),
            )
            return {"success": True, "key": key, "url": self._public_url(key)}
        except ClientError as e:
            self.logger.error("Error al subir imagen: %s", e)
            return {"success": False, "error": str(e)}

    def update(self, old_key: str, file_obj, filename: str, folder: str | None = None) -> dict[str, Any]:
        ext = os.path.splitext(filename)[1].lower()
        if ext not in self.allowed_extensions:
            return {"success": False, "error": f"Extensión no permitida. Permitidas: {', '.join(self.allowed_extensions)}"}

        resolved_folder = folder or old_key.rsplit("/", 1)[0]
        new_key = self._build_key(filename, resolved_folder)

        try:
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=new_key,
                Body=file_obj,
                ContentType=self._content_type(ext),
            )
            self.s3.delete_object(Bucket=self.bucket_name, Key=old_key)
            return {"success": True, "key": new_key, "url": self._public_url(new_key)}
        except ClientError as e:
            self.logger.error("Error al actualizar imagen: %s", e)
            return {"success": False, "error": str(e)}

    def get(self, key: str) -> dict[str, Any]:
        try:
            self.s3.head_object(Bucket=self.bucket_name, Key=key)
            return {"success": True, "key": key, "url": self._public_url(key)}
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("404", "NoSuchKey"):
                return {"success": False, "error": "Imagen no encontrada"}
            self.logger.error("Error al obtener imagen: %s", e)
            return {"success": False, "error": str(e)}

    def presigned_get_url(self, key: str, expires_in: int = 600) -> dict[str, Any]:
        try:
            url = self.s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": key},
                ExpiresIn=expires_in,
            )
            return {"success": True, "key": key, "url": url}
        except ClientError as e:
            self.logger.error("Error al firmar URL de imagen: %s", e)
            return {"success": False, "error": str(e)}

    def list_objects(self, prefix: str = "images/", max_keys: int = 200, continuation_token: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "Bucket": self.bucket_name,
            "MaxKeys": min(max_keys, 1000),
        }
        if prefix:
            params["Prefix"] = prefix
        if continuation_token:
            params["ContinuationToken"] = continuation_token

        response = self.s3.list_objects_v2(**params)
        images = [
            {
                "key": obj["Key"],
                "url": self._public_url(obj["Key"]),
                "size": obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
                "filename": obj["Key"].split("/")[-1],
            }
            for obj in response.get("Contents", [])
            if not obj["Key"].endswith("/")
        ]
        return {
            "images": images,
            "count": len(images),
            "is_truncated": response.get("IsTruncated", False),
            "next_token": response.get("NextContinuationToken"),
        }

    def delete(self, key: str) -> dict[str, Any]:
        try:
            self.s3.delete_object(Bucket=self.bucket_name, Key=key)
            return {"success": True}
        except ClientError as e:
            self.logger.error("Error al eliminar imagen: %s", e)
            return {"success": False, "error": str(e)}


_instance: ImageService | None = None


def get_image_service() -> ImageService:
    global _instance
    if _instance is None:
        _instance = ImageService()
    return _instance
