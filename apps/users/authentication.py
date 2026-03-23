from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, OpenApiExample, inline_serializer

from apps.users.models import User


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    # Override: login with "username" instead of UUID
    username_field = "username"
    username = serializers.CharField()
    tenant_id = serializers.UUIDField(write_only=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remove the "uuid" field that SimpleJWT auto-creates from USERNAME_FIELD
        self.fields.pop("uuid", None)

    def validate(self, attrs):
        tenant_id = attrs.pop("tenant_id", None)
        if not tenant_id:
            raise serializers.ValidationError({"tenant_id": "This field is required."})

        try:
            user = User.objects.all_with_inactive().get(
                tenant_id=tenant_id,
                username=attrs.get("username"),
            )
        except User.DoesNotExist:
            raise serializers.ValidationError({"detail": "Invalid credentials."})

        if not user.active:
            raise serializers.ValidationError({"detail": "User account is disabled."})

        if not user.check_password(attrs.get("password")):
            raise serializers.ValidationError({"detail": "Invalid credentials."})

        # Manually set the user for token generation
        self.user = user
        refresh = self.get_token(user)

        return {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
        }

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["tenant_id"] = str(user.tenant_id)
        token["role"] = user.role
        token["user_id"] = str(user.uuid)
        return token


_token_response = inline_serializer("TokenResponse", fields={
    "refresh": serializers.CharField(),
    "access": serializers.CharField(),
})


@extend_schema(tags=["Auth"])
class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

    @extend_schema(
        summary="Login",
        description="Autentica un usuario con tenant_id, username y password. Devuelve tokens JWT con claims de tenant_id, role y user_id.",
        request=CustomTokenObtainPairSerializer,
        responses={200: _token_response},
        examples=[
            OpenApiExample(
                "Login exitoso",
                value={"tenant_id": "00000000-0000-0000-0000-000000000001", "username": "owner", "password": "owner1234"},
                request_only=True,
            ),
            OpenApiExample(
                "Respuesta exitosa",
                value={"refresh": "eyJhbGciOiJIUzI1NiIs...", "access": "eyJhbGciOiJIUzI1NiIs..."},
                response_only=True,
            ),
        ],
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)
