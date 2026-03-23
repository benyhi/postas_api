from rest_framework import serializers

from apps.users.models import User


class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = [
            "uuid", "tenant_id", "username", "email",
            "password", "role", "active", "created_at", "updated_at",
        ]
        read_only_fields = ["uuid", "tenant_id", "created_at", "updated_at"]

    def create(self, validated_data):
        password = validated_data.pop("password")
        request = self.context["request"]
        validated_data["tenant_id"] = request.tenant_id
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class UserReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "uuid", "username", "email", "role", "active",
            "created_at", "updated_at",
        ]
