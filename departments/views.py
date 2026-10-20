from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts.permissions import ADMIN, OFFICER, IsAdminOrReadOnly, IsStaffRole, get_department, get_role
from analytics import services as analytics
from complaints.models import Complaint
from complaints.serializers import ComplaintListSerializer

from .models import Category, Department
from .serializers import CategorySerializer, DepartmentSerializer


class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [IsAdminOrReadOnly]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def _check_scope(self, request, dept):
        role = get_role(request.user)
        if role == ADMIN:
            return
        if role != OFFICER or get_department(request.user) != dept:
            raise PermissionDenied("Officers can only view their own department.")

    @action(detail=True, methods=["get"])
    def complaints(self, request, pk=None):
        dept = self.get_object()
        self._check_scope(request, dept)
        qs = Complaint.objects.filter(department=dept).exclude(status="DRAFT").select_related("category", "department", "created_by")
        qs = qs.order_by("-priority_score")
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(ComplaintListSerializer(page, many=True, context={"request": request}).data)

    @action(detail=True, methods=["get"])
    def analytics(self, request, pk=None):
        dept = self.get_object()
        self._check_scope(request, dept)
        return Response(analytics.department_analytics(dept))


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.select_related("department")
    serializer_class = CategorySerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    pagination_class = None

    def get_permissions(self):
        return [AllowAny()] if self.action in ("list", "retrieve") else [IsAdminOrReadOnly()]

    def get_queryset(self):
        qs = super().get_queryset()
        if get_role(self.request.user) != ADMIN:
            qs = qs.filter(active=True)
        return qs

    def perform_destroy(self, instance):
        if instance.complaints.exists():  # keep history intact: deactivate instead
            instance.active = False
            instance.save(update_fields=["active"])
        else:
            instance.delete()
