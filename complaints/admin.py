from django.contrib import admin
from .models import AuditLog, Comment, Complaint, ComplaintImage, ComplaintStatusHistory, Upvote

@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ("complaint_number", "title", "status", "priority_level", "department", "ward", "created_at")
    list_filter = ("status", "priority_level", "department", "category")
    search_fields = ("complaint_number", "title", "description")

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "entity_type", "entity_id")
    list_filter = ("action",)
    readonly_fields = [f.name for f in AuditLog._meta.fields]
    def has_add_permission(self, request): return False

admin.site.register([Comment, ComplaintImage, ComplaintStatusHistory, Upvote])
