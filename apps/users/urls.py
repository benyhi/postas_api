from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from drf_spectacular.utils import extend_schema

from apps.users.authentication import CustomTokenObtainPairView
from apps.users.views import UserListCreateView, UserDetailView, PasswordResetRequestView, PasswordResetConfirmView

DecoratedTokenRefreshView = extend_schema(
    summary="Refrescar token",
    description="Obtiene un nuevo access token usando el refresh token.",
    tags=["Auth"],
)(TokenRefreshView)

auth_urlpatterns = [
    path("login/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", DecoratedTokenRefreshView.as_view(), name="token_refresh"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="password_reset_request"),
    path("password-reset/confirm/", PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
]

users_urlpatterns = [
    path("", UserListCreateView.as_view(), name="user-list-create"),
    path("<uuid:uuid>/", UserDetailView.as_view(), name="user-detail"),
]
