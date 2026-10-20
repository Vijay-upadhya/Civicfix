from rest_framework.permissions import BasePermission

CITIZEN, OFFICER, ADMIN = "citizen", "officer", "admin"


def get_role(user):
    if not user or not user.is_authenticated:
        return None
    if user.is_superuser:
        return ADMIN
    profile = getattr(user, "profile", None)
    return profile.role if profile else CITIZEN


def get_department(user):
    profile = getattr(user, "profile", None)
    return profile.department if profile else None


class IsAdminRole(BasePermission):
    message = "Administrator access required."

    def has_permission(self, request, view):
        return get_role(request.user) == ADMIN


class IsStaffRole(BasePermission):
    """Officers and administrators."""
    message = "Officer or administrator access required."

    def has_permission(self, request, view):
        return get_role(request.user) in (OFFICER, ADMIN)


class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return request.user and request.user.is_authenticated
        return get_role(request.user) == ADMIN
