from django.core import signing
from django.conf import settings as django_settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiExample

from apps.notifications.password_reset import send_password_reset_email
from apps.platform_billing.enforcement import check_billing_entitlement
from apps.users.models import User
from apps.users.serializers import UserSerializer, UserReadSerializer
from apps.users.throttles import (
    PasswordResetConfirmRateThrottle,
    PasswordResetIdentityRateThrottle,
    PasswordResetIPRateThrottle,
)
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
        projected_count = User.objects.filter(tenant_id=self.request.tenant_id).count() + 1
        check_billing_entitlement(
            self.request.tenant_id,
            "users",
            resource_count=projected_count,
            context={"source": "users", "operation": "create_user"},
        )
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
        instance.active = False
        instance.save(update_fields=["active"])
        log_action(self.request, "DELETE", "USER", instance.uuid, {
            "username": instance.username,
        })


_RESET_SALT = "postas-password-reset"
_RESET_MAX_AGE = 86400  # 24 hours


def _consume_password_reset(user_pk, reset_token, new_password):
    with transaction.atomic():
        user = User.objects.all_with_inactive().select_for_update().get(pk=user_pk)
        if not default_token_generator.check_token(user, reset_token):
            return False
        validate_password(new_password, user=user)
        user.set_password(new_password)
        user.save(update_fields=['password'])
    return True


@extend_schema(tags=["Auth"])
class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetIPRateThrottle, PasswordResetIdentityRateThrottle]

    @extend_schema(
        summary="Solicitar restablecimiento de contraseña",
        description="Envía un email con un enlace para restablecer la contraseña.",
    )
    def post(self, request):
        email = request.data.get("email", "").strip()
        tenant_id = request.data.get("tenant_id", "").strip()
        _ok_msg = {"detail": "Si existe una cuenta con ese email, recibirás un enlace para restablecer tu contraseña."}

        if not email or not tenant_id:
            return Response({"detail": "email y tenant_id son requeridos."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.all_with_inactive().get(email__iexact=email, tenant_id=tenant_id, active=True)
        except User.DoesNotExist:
            return Response(_ok_msg)

        token = signing.dumps(
            {
                'user_pk': str(user.pk),
                'reset_token': default_token_generator.make_token(user),
            },
            salt=_RESET_SALT,
        )
        reset_url = f'{django_settings.FRONTEND_URL}/reset-password?token={token}'
        send_password_reset_email(user, reset_url)
        return Response(_ok_msg)


@extend_schema(tags=["Auth"])
class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [PasswordResetConfirmRateThrottle]

    @extend_schema(
        summary="Confirmar restablecimiento de contraseña",
        description="Valida el token y establece la nueva contraseña.",
    )
    def post(self, request):
        token = request.data.get("token", "")
        new_password = request.data.get("new_password", "")

        if not token or not new_password:
            return Response({"detail": "token y new_password son requeridos."}, status=status.HTTP_400_BAD_REQUEST)

        if len(new_password) < 8:
            return Response({"detail": "La contraseña debe tener al menos 8 caracteres."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            data = signing.loads(token, salt=_RESET_SALT, max_age=_RESET_MAX_AGE)
            user_pk = data["user_pk"]
            reset_token = data.get('reset_token', '')
            user = User.objects.all_with_inactive().get(pk=user_pk)
        except signing.SignatureExpired:
            return Response({"detail": "El enlace ha expirado. Solicitá uno nuevo."}, status=status.HTTP_400_BAD_REQUEST)
        except (signing.BadSignature, KeyError, User.DoesNotExist, ValueError, TypeError):
            return Response({"detail": "Enlace inválido."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            reset_succeeded = _consume_password_reset(user_pk, reset_token, new_password)
        except DjangoValidationError as exc:
            return Response({'detail': list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        except User.DoesNotExist:
            reset_succeeded = False

        if not reset_succeeded:
            return Response({'detail': 'Enlace invalido.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"detail": "Contraseña restablecida exitosamente."})
