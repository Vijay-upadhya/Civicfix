from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import Role, UserProfile
from .permissions import get_role

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Safe public representation: never includes password or tokens."""
    role = serializers.SerializerMethodField()
    phone_number = serializers.CharField(source="profile.phone_number", required=False, allow_blank=True)
    ward = serializers.CharField(source="profile.ward", required=False, allow_blank=True)
    department = serializers.SerializerMethodField()
    is_verified = serializers.BooleanField(source="profile.is_verified", read_only=True)
    location_consent = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "role", "phone_number", "ward", "department", "is_verified", "location_consent", "date_joined"]
        read_only_fields = ["id", "email", "date_joined"]

    def get_role(self, u):
        return get_role(u)

    def get_location_consent(self, u):
        return u.profile.location_consent_at is not None

    def get_department(self, u):
        d = u.profile.department
        return {"id": d.id, "name": d.name} if d else None

    def update(self, instance, validated):
        profile_data = validated.pop("profile", {})
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        for k, v in profile_data.items():
            setattr(instance.profile, k, v)
        instance.profile.save()
        return instance


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=60)
    last_name = serializers.CharField(max_length=60, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    ward = serializers.CharField(max_length=80, required=False, allow_blank=True)
    accept_policy = serializers.BooleanField()

    def validate_email(self, v):
        v = v.lower()
        if User.objects.filter(username__iexact=v).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return v

    def validate_accept_policy(self, v):
        if not v:
            raise serializers.ValidationError("You must accept the privacy policy.")
        return v

    def validate(self, data):
        validate_password(data["password"])
        return data

    def create(self, data):
        user = User.objects.create_user(username=data["email"], email=data["email"], password=data["password"],
                                        first_name=data["first_name"], last_name=data.get("last_name", ""))
        user.profile.phone_number = data.get("phone_number", "")
        user.profile.ward = data.get("ward", "")
        user.profile.save()  # new accounts are always citizens; roles are changed by administrators only
        return user
