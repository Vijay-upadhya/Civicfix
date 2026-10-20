from django.conf import settings
from PIL import Image
from rest_framework import serializers

from accounts.permissions import ADMIN, OFFICER, get_role
from departments.models import Category, Department

from . import services
from .models import Comment, Complaint, ComplaintImage, ComplaintStatusHistory, Status, TRANSITIONS

ALLOWED_EXT = {".jpg", ".jpeg", ".png"}


def validate_image_file(f):
    """Check extension, size and the real file content (not the browser's content type)."""
    import os
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in ALLOWED_EXT:
        raise serializers.ValidationError("Only JPG, JPEG and PNG images are allowed.")
    if f.size > settings.MAX_IMAGE_BYTES:
        raise serializers.ValidationError("Each image must be 5 MB or smaller.")
    try:
        img = Image.open(f)
        fmt = img.format
        img.verify()
    except Exception:
        raise serializers.ValidationError("The file is not a valid image.")
    if fmt not in ("JPEG", "PNG"):
        raise serializers.ValidationError("Only JPEG and PNG image content is allowed.")
    f.seek(0)
    return f


class CategoryMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "icon"]


class DepartmentMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "name"]


class ImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    uploaded_by = serializers.SerializerMethodField()

    class Meta:
        model = ComplaintImage
        fields = ["id", "url", "caption", "uploaded_by", "is_resolution_evidence", "is_hidden", "created_at"]

    def get_url(self, obj):
        return f"/media/{obj.image.name}"

    def get_uploaded_by(self, obj):
        return obj.uploaded_by.get_full_name() or obj.uploaded_by.username if obj.uploaded_by else None


class CommentSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    author_role = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ["id", "author", "author_role", "text", "is_internal", "is_hidden", "created_at"]

    def get_author(self, obj):
        return obj.author.get_full_name() or obj.author.username

    def get_author_role(self, obj):
        return get_role(obj.author)


class HistorySerializer(serializers.ModelSerializer):
    changed_by = serializers.SerializerMethodField()

    class Meta:
        model = ComplaintStatusHistory
        fields = ["id", "old_status", "new_status", "changed_by", "comment", "created_at"]

    def get_changed_by(self, obj):
        return (obj.changed_by.get_full_name() or obj.changed_by.username) if obj.changed_by else "CivicFix system"


class ComplaintListSerializer(serializers.ModelSerializer):
    category = CategoryMiniSerializer(read_only=True)
    department = DepartmentMiniSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    priority = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    sla = serializers.SerializerMethodField()
    upvotes = serializers.IntegerField(source="upvotes_count", read_only=True)
    has_upvoted = serializers.SerializerMethodField()
    merged_count = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    is_mine = serializers.SerializerMethodField()

    class Meta:
        model = Complaint
        fields = ["id", "complaint_number", "title", "category", "department", "status", "status_display", "priority",
                  "location", "sla", "upvotes", "has_upvoted", "merged_count", "safety_risk", "affected_people",
                  "created_by_name", "is_mine", "submitted_at", "created_at"]

    def get_priority(self, o):
        return {"level": o.priority_level, "score": o.priority_score, "reasons": o.priority_reasons,
                "overridden": o.priority_overridden}

    def get_location(self, o):
        return {"latitude": o.latitude, "longitude": o.longitude, "address": o.address, "ward": o.ward, "landmark": o.landmark}

    def get_sla(self, o):
        return {"deadline": o.sla_deadline, "is_overdue": o.is_overdue, "status": o.sla_status}

    def get_has_upvoted(self, o):
        user = self.context["request"].user
        return o.upvotes.filter(user=user).exists()

    def get_merged_count(self, o):
        return o.merged_children.count()

    def _staff_or_owner(self, o):
        user = self.context["request"].user
        return o.created_by_id == user.pk or get_role(user) in (ADMIN, OFFICER)

    def get_created_by_name(self, o):
        return (o.created_by.get_full_name() or o.created_by.username) if self._staff_or_owner(o) else "Citizen"

    def get_is_mine(self, o):
        return o.created_by_id == self.context["request"].user.pk


class ComplaintDetailSerializer(ComplaintListSerializer):
    images = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()
    history = HistorySerializer(many=True, read_only=True)
    predicted_category = CategoryMiniSerializer(read_only=True)
    assigned_officer = serializers.SerializerMethodField()
    possible_duplicates = serializers.SerializerMethodField()
    parent_complaint = serializers.SerializerMethodField()
    available_actions = serializers.SerializerMethodField()
    age_days = serializers.IntegerField(read_only=True)
    prediction = serializers.SerializerMethodField()

    class Meta(ComplaintListSerializer.Meta):
        fields = ComplaintListSerializer.Meta.fields + [
            "description", "images", "comments", "history", "predicted_category", "prediction", "assigned_officer",
            "possible_duplicates", "parent_complaint", "available_actions", "age_days", "severity", "contact_preference"]

    def get_images(self, o):
        qs = o.images.all()
        if get_role(self.context["request"].user) != ADMIN:
            qs = qs.filter(is_hidden=False)
        return ImageSerializer(qs, many=True).data

    def get_comments(self, o):
        return CommentSerializer(services.visible_comments(o, self.context["request"].user), many=True).data

    def get_assigned_officer(self, o):
        return {"id": o.assigned_officer_id, "name": o.assigned_officer.get_full_name() or o.assigned_officer.username} if o.assigned_officer else None

    def get_possible_duplicates(self, o):
        if o.status in (Status.DRAFT, Status.MERGED, Status.CLOSED, Status.REJECTED) or get_role(self.context["request"].user) == "citizen":
            return o.merged_children.count() if o.status != Status.DRAFT else 0
        return len(services.find_possible_duplicates(latitude=o.latitude, longitude=o.longitude,
                                                     text=f"{o.title} {o.description}", category=o.category, exclude_id=o.pk))

    def get_parent_complaint(self, o):
        return {"id": o.parent_complaint_id, "number": o.parent_complaint.complaint_number} if o.parent_complaint else None

    def get_prediction(self, o):
        if not o.predicted_category_id:
            return None
        return {"category": o.predicted_category.name, "confidence": o.prediction_confidence, "corrected_by_admin": o.category_corrected}

    def get_available_actions(self, o):
        user = self.context["request"].user
        role = get_role(user)
        transitions = [s for s in list(TRANSITIONS[o.status]) + ([Status.REJECTED, Status.MERGED] if role == ADMIN else [])
                       if services.can_transition(o, s, user)]
        return {
            "transitions": transitions,
            "can_comment": o.status != Status.DRAFT,
            "can_internal_note": role in (ADMIN, OFFICER),
            "can_upload_evidence": role in (ADMIN, OFFICER) or (o.created_by_id == user.pk and o.status == Status.DRAFT),
            "can_edit": o.created_by_id == user.pk and o.status == Status.DRAFT,
            "can_admin": role == ADMIN,
            "can_accept": role == OFFICER and o.status == Status.ASSIGNED and services.can_transition(o, Status.IN_PROGRESS, user),
        }


class ComplaintWriteSerializer(serializers.ModelSerializer):
    """Fields a citizen may set while a complaint is still a draft."""
    category = serializers.PrimaryKeyRelatedField(queryset=Category.objects.filter(active=True), required=False, allow_null=True)
    latitude = serializers.FloatField(min_value=-90, max_value=90)
    longitude = serializers.FloatField(min_value=-180, max_value=180)

    class Meta:
        model = Complaint
        fields = ["id", "title", "description", "category", "latitude", "longitude", "address", "ward", "landmark",
                  "contact_preference", "safety_risk", "affected_people"]

    def validate_title(self, v):
        v = v.strip()
        if len(v) < 5:
            raise serializers.ValidationError("Title must contain at least 5 characters.")
        return v

    def validate_description(self, v):
        v = v.strip()
        if len(v) < 20:
            raise serializers.ValidationError("Description must contain at least 20 characters.")
        if len(set(v.lower().replace(" ", ""))) < 5:
            raise serializers.ValidationError("Please describe the problem in meaningful words.")
        return v

    def validate_affected_people(self, v):
        if v < 0:
            raise serializers.ValidationError("Affected people must be zero or more.")
        return v
