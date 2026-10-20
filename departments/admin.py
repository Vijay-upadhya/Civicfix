from django.contrib import admin
from .models import Category, Department

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "department_head", "email", "active")

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "department", "default_severity", "sla_hours", "active")
    list_filter = ("department", "active")
