from rest_framework import serializers

from .models import Category, Department


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "name", "description", "email", "phone", "department_head", "active", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class CategorySerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description", "department", "department_name", "default_severity", "sla_hours",
                  "icon", "active", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]
