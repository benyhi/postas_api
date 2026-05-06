import io
import time

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions.roles import IsAdminOrOwner

from .service import get_image_service


def _get_service():
    try:
        return get_image_service(), None
    except ValueError as e:
        return None, Response(
            {"error": f"Almacenamiento no configurado: {e}"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def _tenant_prefix(tenant_id, sub: str = "") -> str:
    """Construye el prefijo raíz del tenant: '<tenant_id>/<sub>'."""
    base = str(tenant_id)
    return f"{base}/{sub.strip('/')}" if sub else f"{base}/"


def _assert_tenant_key(tenant_id, key: str) -> bool:
    """Verifica que la key pertenezca al tenant (evita acceso cruzado)."""
    return key.startswith(f"{tenant_id}/")


class ImageListUploadView(APIView):
    """
    GET    /api/v1/cloud/images/   → lista imágenes del tenant
    POST   /api/v1/cloud/images/   → sube una imagen al tenant
    DELETE /api/v1/cloud/images/   → elimina una imagen del tenant
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        service, err = _get_service()
        if err:
            return err

        sub_prefix = request.query_params.get("prefix", "")
        prefix = _tenant_prefix(request.tenant_id, sub_prefix)
        search = request.query_params.get("search", "").strip().lower()
        token = request.query_params.get("token") or None
        try:
            max_keys = min(int(request.query_params.get("max_keys", 200)), 1000)
        except ValueError:
            max_keys = 200

        try:
            result = service.list_objects(prefix=prefix, max_keys=max_keys, continuation_token=token)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if search:
            result["images"] = [img for img in result["images"] if search in img["filename"].lower()]
            result["count"] = len(result["images"])

        return Response(result)

    def post(self, request):
        service, err = _get_service()
        if err:
            return err

        image_file = request.FILES.get("image")
        if not image_file:
            return Response(
                {"error": "Se requiere un archivo en el campo 'image'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sub_folder = request.data.get("folder", "images")
        folder = _tenant_prefix(request.tenant_id, sub_folder)
        result = service.upload(image_file, image_file.name, folder=folder)

        if result["success"]:
            return Response(result, status=status.HTTP_201_CREATED)
        return Response({"error": result.get("error")}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request):
        service, err = _get_service()
        if err:
            return err

        key = request.data.get("key") or request.query_params.get("key", "")
        if not key:
            return Response(
                {"error": "Se requiere el parámetro 'key' con la ruta del archivo."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not _assert_tenant_key(request.tenant_id, key):
            return Response({"error": "No autorizado."}, status=status.HTTP_403_FORBIDDEN)

        result = service.delete(key)
        if result["success"]:
            return Response({"deleted": key})
        return Response({"error": result.get("error")}, status=status.HTTP_400_BAD_REQUEST)


class ImageDetailView(APIView):
    """
    GET   /api/v1/cloud/images/<path:key>/   → obtiene metadata de una imagen del tenant
    PUT   /api/v1/cloud/images/<path:key>/   → reemplaza una imagen del tenant
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, key: str):
        service, err = _get_service()
        if err:
            return err

        if not _assert_tenant_key(request.tenant_id, key):
            return Response({"error": "No autorizado."}, status=status.HTTP_403_FORBIDDEN)

        result = service.get(key)
        if result["success"]:
            return Response(result)
        return Response({"error": result.get("error")}, status=status.HTTP_404_NOT_FOUND)

    def put(self, request, key: str):
        service, err = _get_service()
        if err:
            return err

        if not _assert_tenant_key(request.tenant_id, key):
            return Response({"error": "No autorizado."}, status=status.HTTP_403_FORBIDDEN)

        image_file = request.FILES.get("image")
        if not image_file:
            return Response(
                {"error": "Se requiere un archivo en el campo 'image'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        folder = request.data.get("folder") or None
        if folder:
            folder = _tenant_prefix(request.tenant_id, folder)

        result = service.update(key, image_file, image_file.name, folder=folder)

        if result["success"]:
            return Response(result)
        return Response({"error": result.get("error")}, status=status.HTTP_400_BAD_REQUEST)


class PublicImageView(APIView):
    """
    GET /api/v1/cloud/public/images/?tenant_id=<uuid>            → lista imágenes (sin auth)
    GET /api/v1/cloud/public/images/<path:key>/                  → metadata de una imagen (sin auth)
    """

    permission_classes = [AllowAny]

    def get(self, request, key: str | None = None):
        service, err = _get_service()
        if err:
            return err

        if key:
            result = service.get(key)
            if result["success"]:
                return Response(result)
            return Response({"error": result.get("error")}, status=status.HTTP_404_NOT_FOUND)

        tenant_id = request.query_params.get("tenant_id", "")
        if not tenant_id:
            return Response(
                {"error": "Se requiere el parámetro 'tenant_id'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        sub_prefix = request.query_params.get("prefix", "")
        prefix = _tenant_prefix(tenant_id, sub_prefix)
        search = request.query_params.get("search", "").strip().lower()
        token = request.query_params.get("token") or None
        try:
            max_keys = min(int(request.query_params.get("max_keys", 200)), 1000)
        except ValueError:
            max_keys = 200

        try:
            result = service.list_objects(prefix=prefix, max_keys=max_keys, continuation_token=token)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if search:
            result["images"] = [img for img in result["images"] if search in img["filename"].lower()]
            result["count"] = len(result["images"])

        return Response(result)


class BucketHealthView(APIView):
    """
    GET /api/v1/cloud/health/   → prueba conectividad con el bucket (upload -> read -> delete)
    """

    permission_classes = [IsAdminOrOwner]

    def get(self, request):
        steps = []
        overall_ok = True
        probe_key = "__health__/probe.txt"
        probe_body = b"ok"

        def _step(name, fn):
            nonlocal overall_ok
            t0 = time.monotonic()
            try:
                fn()
                steps.append({"step": name, "ok": True, "ms": int((time.monotonic() - t0) * 1000)})
            except Exception as exc:
                steps.append({"step": name, "ok": False, "ms": int((time.monotonic() - t0) * 1000), "error": str(exc)})
                overall_ok = False

        service = None
        t0 = time.monotonic()
        try:
            service = get_image_service()
            steps.append({"step": "connect", "ok": True, "ms": int((time.monotonic() - t0) * 1000), "bucket": service.bucket_name})
        except Exception as exc:
            steps.append({"step": "connect", "ok": False, "ms": int((time.monotonic() - t0) * 1000), "error": str(exc)})
            return Response({"ok": False, "steps": steps})

        _step("upload", lambda: service.s3.put_object(
            Bucket=service.bucket_name, Key=probe_key, Body=io.BytesIO(probe_body), ContentType="text/plain"
        ))
        _step("read", lambda: service.s3.head_object(Bucket=service.bucket_name, Key=probe_key))
        _step("delete", lambda: service.s3.delete_object(Bucket=service.bucket_name, Key=probe_key))

        return Response({"ok": overall_ok, "steps": steps})
