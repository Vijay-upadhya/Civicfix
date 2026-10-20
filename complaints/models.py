import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone

from departments.models import Category, Department, Severity


class Status(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    ASSIGNED = "ASSIGNED", "Assigned"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    WAITING_INFO = "WAITING_INFO", "Waiting for information"
    RESOLVED = "RESOLVED", "Resolved"
    CLOSED = "CLOSED", "Closed"
    REOPENED = "REOPENED", "Reopened"
    REJECTED = "REJECTED", "Rejected"
    MERGED = "MERGED", "Merged"


S = Status
TRANSITIONS = {
    S.DRAFT: [S.SUBMITTED],
    S.SUBMITTED: [S.UNDER_REVIEW],
    S.UNDER_REVIEW: [S.ASSIGNED, S.REJECTED],
    S.ASSIGNED: [S.IN_PROGRESS],
    S.IN_PROGRESS: [S.WAITING_INFO, S.RESOLVED],
    S.WAITING_INFO: [S.IN_PROGRESS],
    S.RESOLVED: [S.CLOSED, S.REOPENED],
    S.REOPENED: [S.ASSIGNED],
    S.CLOSED: [], S.REJECTED: [], S.MERGED: [],
}
# Statuses from which an administrator may reject or merge a complaint.
ACTIVE_STATUSES = [S.SUBMITTED, S.UNDER_REVIEW, S.ASSIGNED, S.IN_PROGRESS, S.WAITING_INFO, S.RESOLVED, S.REOPENED]
# Statuses where the issue still needs work (used for SLA, duplicates, workload).
OPEN_STATUSES = [S.SUBMITTED, S.UNDER_REVIEW, S.ASSIGNED, S.IN_PROGRESS, S.WAITING_INFO, S.REOPENED]


class PriorityLevel(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"
    CRITICAL = "CRITICAL", "Critical"


def image_path(instance, filename):
    ext = Path(filename).suffix.lower() or ".jpg"
    return f"complaints/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{ext}"


class Complaint(models.Model):
    complaint_number = models.CharField(max_length=20, unique=True, null=True, blank=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="complaints")
    title = models.CharField(max_length=200)
    description = models.TextField()
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.PROTECT, related_name="complaints")
    predicted_category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    prediction_confidence = models.FloatField(null=True, blank=True)
    category_corrected = models.BooleanField(default=False, help_text="An administrator changed the category.")
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.PROTECT, related_name="complaints")
    assigned_officer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                         on_delete=models.SET_NULL, related_name="assigned_complaints")
    latitude = models.FloatField()
    longitude = models.FloatField()
    address = models.CharField(max_length=300, blank=True)
    ward = models.CharField(max_length=80, blank=True, db_index=True)
    landmark = models.CharField(max_length=200, blank=True)
    contact_preference = models.CharField(max_length=100, blank=True)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    priority_score = models.PositiveSmallIntegerField(default=0)
    priority_level = models.CharField(max_length=10, choices=PriorityLevel.choices, default=PriorityLevel.LOW)
    priority_reasons = models.JSONField(default=list, blank=True)
    priority_overridden = models.BooleanField(default=False)
    priority_original_score = models.PositiveSmallIntegerField(null=True, blank=True)
    priority_override_reason = models.CharField(max_length=300, blank=True)
    safety_risk = models.BooleanField(default=False)
    affected_people = models.PositiveIntegerField(default=0)
    upvotes_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT, db_index=True)
    is_duplicate = models.BooleanField(default=False)
    parent_complaint = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                         related_name="merged_children")
    sla_deadline = models.DateTimeField(null=True, blank=True)
    sla_24h_notified = models.BooleanField(default=False)
    sla_overdue_notified = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["latitude", "longitude"]), models.Index(fields=["status", "priority_score"])]

    def __str__(self):
        return f"{self.complaint_number or 'Draft #%s' % self.pk}: {self.title}"

    @property
    def display_number(self):
        return self.complaint_number or f"Draft-{self.pk}"

    @property
    def is_overdue(self):
        if not self.sla_deadline or self.status in (S.DRAFT, S.CLOSED, S.REJECTED, S.MERGED):
            return False
        end = self.resolved_at if (self.status == S.RESOLVED and self.resolved_at) else timezone.now()
        return end > self.sla_deadline

    @property
    def sla_status(self):
        if not self.sla_deadline or self.status == S.DRAFT:
            return "No SLA"
        if self.status in (S.REJECTED, S.MERGED):
            return "Not applicable"
        end = self.resolved_at if (self.status in (S.RESOLVED, S.CLOSED) and self.resolved_at) else timezone.now()
        delta = end - self.sla_deadline
        hours = int(abs(delta.total_seconds()) // 3600)
        if self.status in (S.RESOLVED, S.CLOSED):
            return "Resolved within SLA" if delta.total_seconds() <= 0 else f"Resolved {hours} hours late"
        return f"Overdue by {hours} hours" if delta.total_seconds() > 0 else f"{hours} hours remaining"

    @property
    def age_days(self):
        start = self.submitted_at or self.created_at
        return max((timezone.now() - start).days, 0)


class ComplaintImage(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=image_path)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    caption = models.CharField(max_length=200, blank=True)
    is_resolution_evidence = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class ComplaintStatusHistory(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="history")
    old_status = models.CharField(max_length=15, blank=True)
    new_status = models.CharField(max_length=15)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "status history"


class Comment(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments")
    text = models.TextField(max_length=2000)
    is_internal = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]


class Upvote(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="upvotes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="upvotes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["complaint", "user"], name="unique_upvote_per_user")]


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=40, db_index=True)
    entity_type = models.CharField(max_length=40)
    entity_id = models.CharField(max_length=40)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
