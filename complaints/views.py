from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status as http, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from accounts.permissions import ADMIN, CITIZEN, OFFICER, IsAdminRole, IsStaffRole, get_department, get_role
from departments.models import Category, Department
from notifications.services import notify_many, send_complaint_notification

from . import services
from .filters import ComplaintFilter
from .models import Comment, Complaint, ComplaintImage, Status, AuditLog, Upvote
from .serializers import (CommentSerializer, ComplaintDetailSerializer, ComplaintListSerializer,
                          ComplaintWriteSerializer, HistorySerializer, ImageSerializer, validate_image_file)
from django.conf import settings
from django.contrib.auth import get_user_model

S = Status
CITIZEN_EDITABLE = {"title", "description", "category", "latitude", "longitude", "address", "ward", "landmark",
                    "contact_preference", "safety_risk", "affected_people"}
ADMIN_EDITABLE = CITIZEN_EDITABLE | {"severity", "department", "assigned_officer", "priority_score", "priority_override_reason"}
UPVOTE_MILESTONES = {5, 10, 25, 50, 100}


class ComplaintViewSet(viewsets.ModelViewSet):
    filterset_class = ComplaintFilter
    ordering_fields = ["created_at", "submitted_at", "upvotes_count", "priority_score", "sla_deadline"]
    ordering = ["-created_at"]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    throttle_scope = None

    def get_queryset(self):
        return services.visible_complaints(self.request.user)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ComplaintDetailSerializer
        if self.action in ("create",):
            return ComplaintWriteSerializer
        return ComplaintListSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "request": self.request}

    # ---- list with optional nearest sort
    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        if request.query_params.get("ordering") == "nearest":
            try:
                lat, lng = float(request.query_params["lat"]), float(request.query_params["lng"])
            except (KeyError, ValueError):
                raise ValidationError({"lat": "lat and lng are required to sort by nearest."})
            items = sorted(qs[:1000], key=lambda c: services.haversine_m(lat, lng, c.latitude, c.longitude))
            page = self.paginate_queryset(items)
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        ser = ComplaintWriteSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        complaint = ser.save(created_by=request.user)
        return Response(ComplaintDetailSerializer(complaint, context={"request": request}).data, status=http.HTTP_201_CREATED)

    # ---- update: explicit per-role field rules
    def update(self, request, *args, **kwargs):
        complaint = self.get_object()
        role = get_role(request.user)
        data = request.data
        if role == ADMIN:
            allowed = ADMIN_EDITABLE
        elif role == CITIZEN and complaint.created_by_id == request.user.pk and complaint.status == S.DRAFT:
            allowed = CITIZEN_EDITABLE
        else:
            raise PermissionDenied("You cannot edit this complaint.")
        forbidden = [k for k in data.keys() if k not in allowed]
        if forbidden:
            raise PermissionDenied(f"You are not allowed to change: {', '.join(forbidden)}.")
        old_cat, old_dept, old_officer = complaint.category_id, complaint.department_id, complaint.assigned_officer_id
        ser = ComplaintWriteSerializer(complaint, data={k: v for k, v in data.items() if k in CITIZEN_EDITABLE}, partial=True,
                                       context={"request": request})
        ser.is_valid(raise_exception=True)
        complaint = ser.save()
        if role == ADMIN:
            self._apply_admin_changes(request, complaint, data, old_cat, old_dept, old_officer)
        return Response(ComplaintDetailSerializer(complaint, context={"request": request}).data)

    def _apply_admin_changes(self, request, c, data, old_cat, old_dept, old_officer):
        if "severity" in data:
            c.severity = data["severity"]
        if "department" in data:
            c.department = get_object_or_404(Department, pk=data["department"])
        if "assigned_officer" in data:
            c.assigned_officer = get_object_or_404(get_user_model(), pk=data["assigned_officer"]) if data["assigned_officer"] else None
        if c.category_id != old_cat:
            c.category_corrected = True
            if "department" not in data and c.status != S.DRAFT:
                c.department = c.category.department
            if c.submitted_at:
                c.sla_deadline = services.calculate_sla_deadline(c, c.submitted_at)
            services.log_audit(request.user, "CATEGORY_CHANGE", "Complaint", c.pk, {"category": old_cat}, {"category": c.category_id}, request)
        c.save()
        if c.department_id != old_dept or c.assigned_officer_id != old_officer:
            services.log_audit(request.user, "ASSIGNMENT_CHANGE", "Complaint", c.pk,
                               {"department": old_dept, "officer": old_officer},
                               {"department": c.department_id, "officer": c.assigned_officer_id}, request)
        if "priority_score" in data:
            try:
                services.override_priority(c, data["priority_score"], data.get("priority_override_reason", ""), request.user, request)
            except (ValueError, TypeError) as e:
                raise ValidationError({"priority_override_reason": str(e) or "Invalid priority score."})
        elif "severity" in data:
            services.recalculate_priority(c)

    def destroy(self, request, *args, **kwargs):
        c = self.get_object()
        role = get_role(request.user)
        if not (role == ADMIN or (c.created_by_id == request.user.pk and c.status == S.DRAFT)):
            raise PermissionDenied("Only administrators can delete submitted complaints.")
        services.log_audit(request.user, "COMPLAINT_DELETED", "Complaint", c.pk, {"number": c.complaint_number, "title": c.title}, None, request)
        c.delete()
        return Response(status=http.HTTP_204_NO_CONTENT)

    # ---- workflow actions
    def _transition(self, request, new_status, comment="", require_comment=False):
        c = self.get_object()
        comment = (comment or "").strip()
        if require_comment and not comment:
            raise ValidationError({"comment": "A comment is required for this action."})
        try:
            services.create_status_event(c, new_status, request.user, comment, request)
        except services.TransitionError as e:
            raise PermissionDenied(str(e)) if get_role(request.user) else ValidationError(str(e))
        if new_status == S.IN_PROGRESS and not c.assigned_officer_id and get_role(request.user) == OFFICER:
            c.assigned_officer = request.user
            c.save(update_fields=["assigned_officer"])
        return Response(ComplaintDetailSerializer(c, context={"request": request}).data)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        c = self.get_object()
        if c.created_by_id != request.user.pk:
            raise PermissionDenied("Only the owner can submit this complaint.")
        try:
            services.submit_complaint(c, request.user, request)
        except services.TransitionError as e:
            raise ValidationError(str(e))
        c.refresh_from_db()
        return Response(ComplaintDetailSerializer(c, context={"request": request}).data)

    @action(detail=True, methods=["patch"], url_path="status")
    def set_status(self, request, pk=None):
        new = request.data.get("status")
        if new not in S.values:
            raise ValidationError({"status": "Unknown status."})
        needs_comment = new in (S.WAITING_INFO, S.RESOLVED, S.REOPENED, S.REJECTED, S.MERGED)
        return self._transition(request, new, request.data.get("comment", ""), needs_comment)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._transition(request, S.IN_PROGRESS, "Officer accepted the assignment")

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        return self._transition(request, S.RESOLVED, request.data.get("comment", ""), True)

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        return self._transition(request, S.REOPENED, request.data.get("comment", ""), True)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        return self._transition(request, S.CLOSED, request.data.get("comment", "Resolution confirmed"))

    @action(detail=True, methods=["post"], url_path="request-info", permission_classes=[IsStaffRole])
    def request_info(self, request, pk=None):
        msg = (request.data.get("comment") or "").strip()
        if not msg:
            raise ValidationError({"comment": "Describe what information you need."})
        c = self.get_object()
        Comment.objects.create(complaint=c, author=request.user, text=msg)
        send_complaint_notification(c.created_by, c, "info_requested", "More information needed", f"{c.display_number}: {msg[:200]}")
        return self._transition(request, S.WAITING_INFO, msg)

    @action(detail=True, methods=["post"], permission_classes=[IsAdminRole])
    def assign(self, request, pk=None):
        c = self.get_object()
        old = {"department": c.department_id, "officer": c.assigned_officer_id}
        if request.data.get("department"):
            c.department = get_object_or_404(Department, pk=request.data["department"])
            if "officer" not in request.data:
                c.assigned_officer = services.pick_officer(c.department)
        if "officer" in request.data:
            officer = get_object_or_404(get_user_model(), pk=request.data["officer"]) if request.data["officer"] else None
            if officer and get_role(officer) != OFFICER:
                raise ValidationError({"officer": "User is not an officer."})
            c.assigned_officer = officer
        c.save()
        services.log_audit(request.user, "ASSIGNMENT_CHANGE", "Complaint", c.pk, old,
                           {"department": c.department_id, "officer": c.assigned_officer_id}, request)
        notify_many([c.assigned_officer], c, "assigned", "Complaint assigned to you", f"{c.display_number}: {c.title}")
        send_complaint_notification(c.created_by, c, "assigned", "Complaint assigned",
                                    f"Your complaint {c.display_number} has been assigned to {c.department.name}.")
        return Response(ComplaintDetailSerializer(c, context={"request": request}).data)

    @action(detail=True, methods=["post"], permission_classes=[IsAdminRole])
    def merge(self, request, pk=None):
        parent = self.get_object()
        ids = request.data.get("duplicate_ids") or []
        children = list(Complaint.objects.filter(pk__in=ids))
        if not children:
            raise ValidationError({"duplicate_ids": "Provide the ids of complaints to merge into this one."})
        merged = services.merge_duplicate_complaints(parent, children, request.user, request.data.get("reason", ""), request)
        return Response({"merged": merged, "parent": parent.display_number})

    # ---- social actions
    @action(detail=True, methods=["post", "delete"])
    def upvote(self, request, pk=None):
        c = self.get_object()
        if c.status == S.DRAFT:
            raise ValidationError("Drafts cannot be upvoted.")
        if request.method == "POST":
            try:
                with transaction.atomic():
                    Upvote.objects.create(complaint=c, user=request.user)
            except IntegrityError:
                raise ValidationError("You have already upvoted this complaint.")
        else:
            Upvote.objects.filter(complaint=c, user=request.user).delete()
        c.upvotes_count = c.upvotes.count()
        c.save(update_fields=["upvotes_count"])
        services.recalculate_priority(c)
        if request.method == "POST" and c.upvotes_count in UPVOTE_MILESTONES:
            send_complaint_notification(c.created_by, c, "upvote_milestone", "Your complaint is getting support",
                                        f"{c.display_number} now has {c.upvotes_count} upvotes.")
        return Response({"upvotes": c.upvotes_count, "has_upvoted": request.method == "POST"})

    @action(detail=True, methods=["post"])
    def comment(self, request, pk=None):
        c = self.get_object()
        if c.status == S.DRAFT:
            raise ValidationError("Comments open after the complaint is submitted.")
        text = (request.data.get("text") or "").strip()
        if not text:
            raise ValidationError({"text": "Comment cannot be empty."})
        internal = str(request.data.get("is_internal", "")).lower() in ("true", "1")
        role = get_role(request.user)
        if internal and role not in (ADMIN, OFFICER):
            raise PermissionDenied("Only officers and administrators can add internal notes.")
        comment = Comment.objects.create(complaint=c, author=request.user, text=text[:2000], is_internal=internal)
        if not internal:
            targets = [c.created_by, c.assigned_officer]
            notify_many([u for u in targets if u and u.pk != request.user.pk], c, "comment", "New comment",
                        f"New comment on {c.display_number}.")
            if c.status == S.WAITING_INFO and c.created_by_id == request.user.pk:
                services.create_status_event(c, S.IN_PROGRESS, None, "Citizen replied with the requested information")
        return Response(CommentSerializer(comment).data, status=http.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="report")
    def report_content(self, request, pk=None):
        c = self.get_object()
        reason = (request.data.get("reason") or "No reason given")[:300]
        services.log_audit(request.user, "CONTENT_REPORTED", "Complaint", c.pk, None,
                           {"reason": reason, "comment_id": request.data.get("comment_id")}, request)
        admins = get_user_model().objects.filter(Q(is_superuser=True) | Q(profile__role=ADMIN)).distinct()
        notify_many(admins, c, "content_reported", "Content reported", f"{c.display_number} was reported: {reason}")
        return Response({"detail": "Thanks. An administrator will review this."}, status=http.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        return Response(HistorySerializer(self.get_object().history.all(), many=True).data)

    @action(detail=True, methods=["get"])
    def duplicates(self, request, pk=None):
        if get_role(request.user) == CITIZEN:
            raise PermissionDenied("Only staff can view duplicate analysis.")
        c = self.get_object()
        found = services.find_possible_duplicates(latitude=c.latitude, longitude=c.longitude,
                                                  text=f"{c.title} {c.description}", category=c.category, exclude_id=c.pk)
        return Response([{"similarity": f["similarity"], "distance_m": f["distance_m"],
                          "complaint": ComplaintListSerializer(f["complaint"], context={"request": request}).data} for f in found])

    @action(detail=True, methods=["post"], url_path="images", throttle_scope="upload")
    def images(self, request, pk=None):
        c = self.get_object()
        role = get_role(request.user)
        evidence = str(request.data.get("is_resolution_evidence", "")).lower() in ("true", "1")
        owner_draft = c.created_by_id == request.user.pk and c.status == S.DRAFT
        staff_ok = role == ADMIN or (role == OFFICER and get_department(request.user) and c.department_id == get_department(request.user).pk)
        if not (owner_draft or (staff_ok and evidence)):
            raise PermissionDenied("You cannot upload images to this complaint.")
        file = request.FILES.get("image")
        if not file:
            raise ValidationError({"image": "No file uploaded."})
        if c.images.filter(is_resolution_evidence=evidence).count() >= settings.MAX_IMAGES_PER_COMPLAINT:
            raise ValidationError({"image": f"A maximum of {settings.MAX_IMAGES_PER_COMPLAINT} images is allowed."})
        try:
            validate_image_file(file)
        except Exception as e:
            raise ValidationError({"image": getattr(e, "detail", str(e))})
        img = ComplaintImage.objects.create(complaint=c, image=file, uploaded_by=request.user,
                                            caption=(request.data.get("caption") or "")[:200], is_resolution_evidence=evidence)
        return Response(ImageSerializer(img).data, status=http.HTTP_201_CREATED)


def _hide(request, obj, entity, flag_field="is_hidden"):
    old = getattr(obj, flag_field)
    new = str(request.data.get("hidden", "true")).lower() in ("true", "1")
    setattr(obj, flag_field, new)
    obj.save(update_fields=[flag_field])
    services.log_audit(request.user, "CONTENT_MODERATION", entity, obj.pk, {"hidden": old}, {"hidden": new, "reason": request.data.get("reason", "")}, request)
    return Response({"id": obj.pk, "hidden": new})


@api_view(["PATCH"])
@permission_classes([IsAdminRole])
def hide_comment(request, pk):
    return _hide(request, get_object_or_404(Comment, pk=pk), "Comment")


@api_view(["PATCH"])
@permission_classes([IsAdminRole])
def hide_image(request, pk):
    return _hide(request, get_object_or_404(ComplaintImage, pk=pk), "ComplaintImage")


@api_view(["GET"])
@permission_classes([IsAdminRole])
def audit_logs(request):
    from rest_framework.pagination import PageNumberPagination
    qs = AuditLog.objects.select_related("actor")
    if request.query_params.get("action"):
        qs = qs.filter(action=request.query_params["action"])
    pager = PageNumberPagination()
    pager.page_size = 30
    page = pager.paginate_queryset(qs, request)
    data = [{"id": a.id, "actor": a.actor.username if a.actor else "system", "action": a.action, "entity_type": a.entity_type,
             "entity_id": a.entity_id, "old_value": a.old_value, "new_value": a.new_value, "ip_address": a.ip_address,
             "created_at": a.created_at} for a in page]
    return pager.get_paginated_response(data)


# ---- intelligence endpoints
@api_view(["POST"])
def classify(request):
    text = f"{request.data.get('title', '')}. {request.data.get('description', '')}".strip(". ")
    if len(text) < 5:
        raise ValidationError("Provide a title or description.")
    r = services.classify_complaint(text)
    cat = r["category"]
    dept = cat.department if cat and not r["low_confidence"] else services.general_review_department()
    return Response({
        "category": {"id": cat.id, "name": cat.name, "slug": cat.slug} if cat else None,
        "confidence": r["confidence"], "method": r["method"], "low_confidence": r["low_confidence"],
        "top_two": r["top_two"], "explanation": r["explanation"],
        "department": {"id": dept.id, "name": dept.name} if dept else None,
        "sla_hours": cat.sla_hours if cat else 240, "severity": cat.default_severity if cat else "MEDIUM"})


@api_view(["POST"])
def check_duplicates(request):
    try:
        lat, lng = float(request.data["latitude"]), float(request.data["longitude"])
    except (KeyError, ValueError, TypeError):
        raise ValidationError("latitude and longitude are required.")
    category = Category.objects.filter(pk=request.data.get("category")).first() if request.data.get("category") else None
    text = f"{request.data.get('title', '')} {request.data.get('description', '')}"
    found = services.find_possible_duplicates(latitude=lat, longitude=lng, text=text, category=category)
    return Response({"count": len(found), "results": [
        {"id": f["complaint"].id, "complaint_number": f["complaint"].complaint_number, "title": f["complaint"].title,
         "status": f["complaint"].status, "similarity": f["similarity"], "distance_m": f["distance_m"],
         "upvotes": f["complaint"].upvotes_count} for f in found]})


@api_view(["POST"])
def calculate_priority(request):
    d = request.data
    category = Category.objects.filter(pk=d.get("category")).first() if d.get("category") else None
    try:
        result = services.calculate_priority(
            severity=d.get("severity") or (category.default_severity if category else "MEDIUM"),
            safety_risk=str(d.get("safety_risk", "")).lower() in ("true", "1"),
            affected_people=int(d.get("affected_people") or 0), upvotes=int(d.get("upvotes") or 0),
            duplicates=int(d.get("duplicates") or 0), days_unresolved=int(d.get("days_unresolved") or 0),
            category_slug=category.slug if category else d.get("category_slug"),
            location_text=f"{d.get('title', '')} {d.get('description', '')} {d.get('landmark', '')}")
    except ValueError:
        raise ValidationError("Numeric fields must be numbers.")
    return Response(result)
