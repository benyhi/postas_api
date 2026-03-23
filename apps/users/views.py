from rest_framework import generics, status
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample

from apps.users.models import User
from apps.users.serializers import UserSerializer, UserReadSerializer
from core.permissions.roles import IsOwner
from core.utils.audit import log_action


@extend_schema_view(
    list=extend_schema(
        summary="Listar usuarios",
        description="Devuelve la lista paginada de usuarios del tenant actual. Solo OWNER.",
        tags=["Users"],
        responses={200: UserReadSerializer(many=True)},
    ),
    create=extend_schema(
        summary="Crear usuario",
        description="Crea un nuevo usuario para el tenant actual. Solo OWNER.",
        tags=["Users"],
        request=UserSerializer,
        responses={201: UserReadSerializer},
        examples=[
            OpenApiExample(
                "Crear usuario",
                value={"username": "nuevo_user", "email": "user@mail.com", "password": "secret1234", "role": "EMPLOYEE"},
                request_only=True,
            ),
        ],
    ),
)
class UserListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsOwner]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return UserSerializer
        return UserReadSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return User.objects.none()
        return User.objects.filter(tenant_id=self.request.tenant_id)

    def perform_create(self, serializer):
        user = serializer.save()
        log_action(self.request, "CREATE", "USER", user.uuid, {
            "username": user.username, "role": user.role,
        })


@extend_schema_view(
    retrieve=extend_schema(
        summary="Obtener usuario",
        description="Devuelve el detalle de un usuario por UUID.",
        tags=["Users"],
    ),
    update=extend_schema(
        summary="Actualizar usuario (PUT)",
        description="Actualiza todos los campos de un usuario.",
        tags=["Users"],
        request=UserSerializer,
        responses={200: UserReadSerializer},
    ),
    partial_update=extend_schema(
        summary="Actualizar usuario (PATCH)",
        description="Actualiza parcialmente un usuario.",
        tags=["Users"],
        request=UserSerializer,
        responses={200: UserReadSerializer},
    ),
    destroy=extend_schema(
        summary="Eliminar usuario (soft delete)",
        description="Desactiva el usuario (soft delete). No elimina el registro.",
        tags=["Users"],
    ),
)
class UserDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsOwner]
    lookup_field = "uuid"

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return UserSerializer
        return UserReadSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return User.objects.none()
        return User.objects.filter(tenant_id=self.request.tenant_id)

    def perform_update(self, serializer):
        user = serializer.save()
        log_action(self.request, "UPDATE", "USER", user.uuid, {
            "username": user.username, "role": user.role,
        })

    def perform_destroy(self, instance):
        # Soft delete
        instance.active = False
        instance.save(update_fields=["active"])
        log_action(self.request, "DELETE", "USER", instance.uuid, {
            "username": instance.username,
        })
