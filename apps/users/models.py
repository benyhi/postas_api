import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

from core.models.tenant_model import TenantModel


class UserManager(BaseUserManager):
    def get_queryset(self):
        return super().get_queryset().filter(active=True)

    def all_with_inactive(self):
        return super().get_queryset()

    def create_user(self, username, email, password=None, **extra_fields):
        if not username:
            raise ValueError("Username is required")
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault("role", "OWNER")
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("tenant_id", uuid.uuid4())
        return self.create_user(username, email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, TenantModel):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        ADMIN = "ADMIN", "Admin"
        EMPLOYEE = "EMPLOYEE", "Employee"

    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=150)
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.EMPLOYEE)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "uuid"
    REQUIRED_FIELDS = ["username", "email"]

    class Meta:
        db_table = "users"
        constraints = [
            models.UniqueConstraint(fields=["tenant_id", "username"], name="unique_tenant_username"),
            models.UniqueConstraint(fields=["tenant_id", "email"], name="unique_tenant_email"),
        ]

    def __str__(self):
        return f"{self.username} ({self.tenant_id})"
