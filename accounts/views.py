from django.contrib.auth import authenticate, get_user_model, login, logout
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from complaints.services import log_audit
from departments.models import Department

from .models import PrivacyPolicyAcceptance, Role
from .permissions import IsAdminRole, get_role
from .serializers import RegisterSerializer, UserSerializer
from django.conf import settings

User = get_user_model()


def client_ip(request):
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")) or None


class AuthThrottleMixin:
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class RegisterView(AuthThrottleMixin, APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        ser = RegisterSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = ser.save()
        PrivacyPolicyAcceptance.objects.create(user=user, policy_version=settings.POLICY_VERSION, ip_address=client_ip(request))
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data}, status=status.HTTP_201_CREATED)


class LoginView(AuthThrottleMixin, APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        ident = (request.data.get("email") or request.data.get("username") or "").strip().lower()
        user = authenticate(request, username=ident, password=request.data.get("password") or "")
        if not user:
            raise ValidationError({"detail": "Incorrect email or password."})
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": UserSerializer(user).data})


class LogoutView(APIView):
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class LocationConsentView(APIView):
    """Record (or withdraw) the user's permission to use location features and third-party map services."""

    def post(self, request):
        granted = str(request.data.get("granted", "")).lower() in ("true", "1")
        request.user.profile.location_consent_at = timezone.now() if granted else None
        request.user.profile.save(update_fields=["location_consent_at"])
        log_audit(request.user, "LOCATION_CONSENT", "User", request.user.pk, None, {"granted": granted}, request)
        return Response({"location_consent": granted})


class UserListView(generics.ListAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = UserSerializer
    filterset_fields = []

    def get_queryset(self):
        qs = User.objects.select_related("profile", "profile__department").order_by("id")
        role, q = self.request.query_params.get("role"), self.request.query_params.get("search")
        if role:
            qs = qs.filter(profile__role=role)
        if q:
            qs = qs.filter(Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
        return qs


class UserDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAdminRole]
    serializer_class = UserSerializer
    queryset = User.objects.select_related("profile")


@api_view(["PATCH"])
@permission_classes([IsAdminRole])
def change_role(request, pk):
    user = get_object_or_404(User, pk=pk)
    role = request.data.get("role")
    if role not in Role.values:
        raise ValidationError({"role": f"Choose one of {', '.join(Role.values)}."})
    if user.pk == request.user.pk and role != Role.ADMIN:
        raise ValidationError({"role": "You cannot remove your own administrator role."})
    old = {"role": user.profile.role, "department": user.profile.department_id}
    user.profile.role = role
    if "department" in request.data:
        user.profile.department = get_object_or_404(Department, pk=request.data["department"]) if request.data["department"] else None
    if role == Role.OFFICER and not user.profile.department_id:
        raise ValidationError({"department": "Officers must belong to a department."})
    user.profile.save()
    log_audit(request.user, "USER_ROLE_CHANGE", "User", user.pk, old, {"role": role, "department": user.profile.department_id}, request)
    return Response(UserSerializer(user).data)
