"""Business logic for CivicFix. Views stay thin and call these functions."""
import math
import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from accounts.permissions import ADMIN, CITIZEN, OFFICER, get_department, get_role
from departments.models import Category, Department
from ml_classifier import predictor
from notifications.services import notify_many, send_complaint_notification

from .models import (ACTIVE_STATUSES, OPEN_STATUSES, TRANSITIONS, AuditLog, Complaint,
                     ComplaintStatusHistory, Status)

S = Status


class TransitionError(Exception):
    pass


# ---------------------------------------------------------------- audit
def log_audit(actor, action, entity_type, entity_id, old=None, new=None, request=None):
    ip = None
    if request is not None:
        fwd = request.META.get("HTTP_X_FORWARDED_FOR")
        ip = (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")) or None
    return AuditLog.objects.create(actor=actor if getattr(actor, "pk", None) else None, action=action,
                                   entity_type=entity_type, entity_id=str(entity_id),
                                   old_value=old, new_value=new, ip_address=ip)


# ---------------------------------------------------------------- classification & routing
def classify_complaint(text: str, category_hint: Category | None = None):
    """Predict a category for free text. Never rejects; low confidence -> General Review."""
    result = predictor.predict(text, settings.CLASSIFIER_CONFIDENCE_THRESHOLD)
    categories = {c.slug: c for c in Category.objects.filter(active=True).select_related("department")}
    category = categories.get(result["label"]) if result["label"] else None
    top_two = [{"slug": s, "name": categories[s].name if s in categories else s, "confidence": p}
               for s, p in result["top"]]
    return {"category": category, "confidence": result["confidence"], "method": result["method"],
            "low_confidence": result["low_confidence"] or category is None,
            "top_two": top_two, "explanation": result["explanation"]}


def general_review_department():
    return Department.objects.filter(name__icontains="General Review").first()


def assign_department(complaint, classification=None):
    """Choose the department. A citizen-chosen category wins; otherwise use the prediction."""
    if complaint.category_id:
        return complaint.category.department
    if classification and classification["category"] and not classification["low_confidence"]:
        return classification["category"].department
    return general_review_department()


def pick_officer(department):
    """Least-loaded active officer in the department (None if the department has no officers)."""
    if not department:
        return None
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return (User.objects.filter(profile__role=OFFICER, profile__department=department, is_active=True)
            .annotate(load=Count("assigned_complaints", filter=Q(assigned_complaints__status__in=OPEN_STATUSES)))
            .order_by("load", "id").first())


# ---------------------------------------------------------------- SLA
def calculate_sla_deadline(complaint, start=None):
    start = start or complaint.submitted_at or timezone.now()
    hours = complaint.category.sla_hours if complaint.category_id else 240
    if complaint.safety_risk or complaint.priority_level == "CRITICAL":
        hours = min(hours, 24)  # critical safety issues: 24 hours
    return start + timedelta(hours=hours)


# ---------------------------------------------------------------- priority
SEVERITY_POINTS = {"LOW": 5, "MEDIUM": 12, "HIGH": 20, "CRITICAL": 30}
CATEGORY_WEIGHT = {"safety": 6, "traffic": 4, "water": 3, "drain": 3, "streetlight": 2, "pothole": 2}
HIGH_TRAFFIC_WORDS = ("main road", "highway", "metro", "school", "hospital", "junction", "market", "bus stop")


def priority_level_for(score):
    return "CRITICAL" if score >= 80 else "HIGH" if score >= 60 else "MEDIUM" if score >= 30 else "LOW"


def calculate_priority(*, severity="MEDIUM", safety_risk=False, affected_people=0, upvotes=0, duplicates=0,
                       days_unresolved=0, category_slug=None, location_text=""):
    """Explainable 0-100 score. Returns {score, level, reasons, breakdown}."""
    parts, reasons = {}, []
    parts["severity"] = SEVERITY_POINTS.get(severity, 12)
    reasons.append(f"{severity.title()} default severity (+{parts['severity']})")
    parts["safety"] = 20 if safety_risk else 0
    if safety_risk:
        reasons.append("Marked as a safety risk (+20)")
    n = affected_people
    parts["affected"] = 0 if n <= 0 else 3 if n < 5 else 7 if n < 20 else 11 if n < 100 else 15
    if parts["affected"]:
        reasons.append(f"Affects about {n} people (+{parts['affected']})")
    parts["upvotes"] = min(15, upvotes)
    if upvotes:
        reasons.append(f"{upvotes} upvote{'s' if upvotes != 1 else ''} (+{parts['upvotes']})")
    parts["age"] = min(10, max(days_unresolved, 0) * 2)
    if parts["age"]:
        reasons.append(f"Unresolved for {days_unresolved} day{'s' if days_unresolved != 1 else ''} (+{parts['age']})")
    parts["duplicates"] = min(10, duplicates * 2)
    if duplicates:
        reasons.append(f"{duplicates} duplicate report{'s' if duplicates != 1 else ''} merged (+{parts['duplicates']})")
    text = (location_text or "").lower()
    parts["location"] = 5 if any(w in text for w in HIGH_TRAFFIC_WORDS) else 0
    if parts["location"]:
        reasons.append("Located at a high-footfall place such as a main road, school or hospital (+5)")
    parts["category"] = CATEGORY_WEIGHT.get(category_slug or "", 0)
    if parts["category"]:
        reasons.append(f"Category weight (+{parts['category']})")
    score = min(100, sum(parts.values()))
    return {"score": score, "level": priority_level_for(score), "reasons": reasons, "breakdown": parts}


def recalculate_priority(complaint, save=True):
    """Recompute the score unless an administrator overrode it."""
    if complaint.priority_overridden:
        return complaint
    r = calculate_priority(
        severity=complaint.severity, safety_risk=complaint.safety_risk, affected_people=complaint.affected_people,
        upvotes=complaint.upvotes_count, duplicates=complaint.merged_children.count() if complaint.pk else 0,
        days_unresolved=complaint.age_days if complaint.submitted_at else 0,
        category_slug=complaint.category.slug if complaint.category_id else None,
        location_text=f"{complaint.title} {complaint.description} {complaint.landmark} {complaint.address}")
    complaint.priority_score, complaint.priority_level, complaint.priority_reasons = r["score"], r["level"], r["reasons"]
    if save:
        complaint.save(update_fields=["priority_score", "priority_level", "priority_reasons", "updated_at"])
    return complaint


def override_priority(complaint, score, reason, actor, request=None):
    if not reason:
        raise ValueError("An override reason is required.")
    old = {"score": complaint.priority_score, "level": complaint.priority_level}
    if not complaint.priority_overridden:
        complaint.priority_original_score = complaint.priority_score
    complaint.priority_overridden = True
    complaint.priority_score = max(0, min(100, int(score)))
    complaint.priority_level = priority_level_for(complaint.priority_score)
    complaint.priority_override_reason = reason
    complaint.priority_reasons = [f"Administrator override: {reason}"] + [r for r in complaint.priority_reasons
                                                                         if not r.startswith("Administrator override")]
    complaint.save()
    log_audit(actor, "PRIORITY_CHANGE", "Complaint", complaint.pk, old,
              {"score": complaint.priority_score, "level": complaint.priority_level, "reason": reason}, request)


# ---------------------------------------------------------------- duplicates
def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bounding_box(lat, lng, radius_m):
    dlat = radius_m / 111_320
    dlng = radius_m / (111_320 * max(math.cos(math.radians(lat)), 0.01))
    return lat - dlat, lat + dlat, lng - dlng, lng + dlng


def find_possible_duplicates(*, latitude, longitude, text, category=None, exclude_id=None, limit=5):
    """Unresolved complaints within 200 m and 30 days, scored by text, category and proximity."""
    radius = settings.DUPLICATE_RADIUS_METERS
    south, north, west, east = bounding_box(latitude, longitude, radius)
    since = timezone.now() - timedelta(days=settings.DUPLICATE_WINDOW_DAYS)
    qs = (Complaint.objects.filter(latitude__range=(south, north), longitude__range=(west, east),
                                   status__in=OPEN_STATUSES, created_at__gte=since, parent_complaint__isnull=True)
          .select_related("category"))
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    candidates = []
    for c in qs:
        d = haversine_m(latitude, longitude, c.latitude, c.longitude)
        if d <= radius:
            candidates.append((c, d))
    if not candidates:
        return []
    docs = [text] + [f"{c.title} {c.description}" for c, _ in candidates]
    try:
        tfidf = TfidfVectorizer(stop_words="english").fit_transform(docs)
        sims = cosine_similarity(tfidf[0:1], tfidf[1:])[0]
    except ValueError:  # empty vocabulary
        sims = [0.0] * len(candidates)
    results = []
    for (c, d), sim in zip(candidates, sims):
        same_cat = bool(category and c.category_id == getattr(category, "pk", category))
        score = sim * 60 + (20 if same_cat else 0) + 20 * (1 - d / radius)
        if score >= 40 and (sim >= 0.2 or same_cat):
            results.append({"complaint": c, "similarity": round(min(score, 100)), "distance_m": round(d)})
    return sorted(results, key=lambda r: -r["similarity"])[:limit]


@transaction.atomic
def merge_duplicate_complaints(parent, children, actor, reason="", request=None):
    """Merge `children` into `parent`; histories are preserved and one audit record is written."""
    merged = []
    for child in children:
        if child.pk == parent.pk or child.status == S.MERGED or child.status not in ACTIVE_STATUSES:
            continue
        child.is_duplicate, child.parent_complaint = True, parent
        child.save(update_fields=["is_duplicate", "parent_complaint", "updated_at"])
        create_status_event(child, S.MERGED, actor, f"Merged into {parent.display_number}. {reason}".strip())
        send_complaint_notification(child.created_by, child, "merged", "Your complaint was merged",
                                    f"{child.display_number} was merged into {parent.display_number}, which covers the same issue.")
        merged.append(child.pk)
    if merged:
        recalculate_priority(parent)
        log_audit(actor, "COMPLAINT_MERGE", "Complaint", parent.pk, None,
                  {"merged_ids": merged, "reason": reason}, request)
    return merged


# ---------------------------------------------------------------- status workflow
OFFICER_MOVES = {(S.ASSIGNED, S.IN_PROGRESS), (S.IN_PROGRESS, S.WAITING_INFO), (S.WAITING_INFO, S.IN_PROGRESS),
                 (S.IN_PROGRESS, S.RESOLVED), (S.REOPENED, S.ASSIGNED)}
CITIZEN_MOVES = {(S.DRAFT, S.SUBMITTED), (S.RESOLVED, S.CLOSED), (S.RESOLVED, S.REOPENED)}


def can_transition(complaint, new_status, actor):
    """Whether `actor` (None = the system) may move the complaint to `new_status`."""
    old, new = complaint.status, new_status
    role = get_role(actor) if actor else "system"
    if new in (S.REJECTED, S.MERGED):
        return role == ADMIN and old in ACTIVE_STATUSES
    if new not in TRANSITIONS.get(old, []):
        return False
    if role in (ADMIN, "system"):
        return True
    if role == OFFICER:
        dept = get_department(actor)
        return (old, new) in OFFICER_MOVES and dept is not None and complaint.department_id == dept.pk
    if role == CITIZEN:
        return (old, new) in CITIZEN_MOVES and complaint.created_by_id == actor.pk
    return False


STATUS_MESSAGES = {
    S.IN_PROGRESS: "work has started", S.WAITING_INFO: "more information is needed from you",
    S.RESOLVED: "was marked resolved. Please confirm or reopen it", S.CLOSED: "was closed",
    S.REOPENED: "was reopened", S.REJECTED: "was rejected",
}


@transaction.atomic
def create_status_event(complaint, new_status, actor=None, comment="", request=None):
    """Validate and apply a status change, write history, audit log and notifications."""
    if not can_transition(complaint, new_status, actor):
        raise TransitionError(f"{complaint.status} -> {new_status} is not allowed for this user.")
    old = complaint.status
    now = timezone.now()
    complaint.status = new_status
    if new_status == S.ASSIGNED:
        complaint.assigned_at = now
    elif new_status == S.RESOLVED:
        complaint.resolved_at = now
    elif new_status == S.CLOSED:
        complaint.closed_at = now
    elif new_status == S.REOPENED:
        complaint.closed_at = None
        complaint.sla_deadline = now + timedelta(hours=min(complaint.category.sla_hours if complaint.category_id else 72, 72))
        complaint.sla_24h_notified = complaint.sla_overdue_notified = False
    complaint.save()
    history = ComplaintStatusHistory.objects.create(complaint=complaint, old_status=old, new_status=new_status,
                                                    changed_by=actor, comment=comment)
    log_audit(actor, "STATUS_CHANGE", "Complaint", complaint.pk, {"status": old}, {"status": new_status, "comment": comment}, request)
    if new_status in STATUS_MESSAGES:
        send_complaint_notification(complaint.created_by, complaint, "status_changed", f"{complaint.display_number}: {new_status.replace('_', ' ').title()}",
                                    f"Your complaint {complaint.display_number} {STATUS_MESSAGES[new_status]}.")
    if new_status == S.REOPENED:
        notify_many([complaint.assigned_officer], complaint, "reopened", "Complaint reopened",
                    f"{complaint.display_number} was reopened by the citizen.")
    return history


def submit_complaint(complaint, actor, request=None):
    """Draft -> Submitted -> Under review -> Assigned. Classifies, routes, scores and sets the SLA."""
    with transaction.atomic():
        if complaint.status != S.DRAFT:
            raise TransitionError("Only draft complaints can be submitted.")
        text = f"{complaint.title}. {complaint.description}"
        cls = classify_complaint(text)
        complaint.predicted_category = cls["category"]
        complaint.prediction_confidence = cls["confidence"] if cls["category"] else None
        if not complaint.category_id:  # citizen chose "I am not sure"
            if cls["category"] and not cls["low_confidence"]:
                complaint.category = cls["category"]
            else:
                complaint.category = Category.objects.filter(slug="other").first()
        complaint.department = assign_department(complaint, cls) or complaint.category.department
        if complaint.severity == "MEDIUM" and complaint.category_id:
            complaint.severity = complaint.category.default_severity
        complaint.submitted_at = timezone.now()
        complaint.complaint_number = f"CF-{complaint.submitted_at:%Y}-{complaint.pk:06d}"
        recalculate_priority(complaint, save=False)
        complaint.sla_deadline = calculate_sla_deadline(complaint, complaint.submitted_at)
        complaint.save()
        create_status_event(complaint, S.SUBMITTED, actor, "Complaint submitted", request)
        create_status_event(complaint, S.UNDER_REVIEW, None, "Automatic validation and routing")
        complaint.assigned_officer = pick_officer(complaint.department)
        complaint.save(update_fields=["assigned_officer", "updated_at"])
        create_status_event(complaint, S.ASSIGNED, None, f"Routed to {complaint.department.name}")
    send_complaint_notification(complaint.created_by, complaint, "submitted", "Complaint submitted",
                                f"Your complaint {complaint.complaint_number} has been assigned to {complaint.department.name}.")
    staff = [complaint.assigned_officer] if complaint.assigned_officer else [o.user for o in complaint.department.officers.select_related("user")]
    notify_many(staff, complaint, "assigned", "New complaint assigned",
                f"{complaint.complaint_number}: {complaint.title} ({complaint.priority_level.title()} priority).")
    return complaint


# ---------------------------------------------------------------- visibility
def visible_complaints(user):
    """Queryset of complaints this user is allowed to see."""
    qs = Complaint.objects.select_related("category", "department", "assigned_officer", "created_by")
    role = get_role(user)
    if role == ADMIN:
        return qs
    if role == OFFICER:
        dept = get_department(user)
        return qs.filter(department=dept).exclude(status=S.DRAFT) if dept else qs.none()
    return qs.filter(Q(created_by=user) | ~Q(status__in=[S.DRAFT, S.REJECTED]))


def visible_comments(complaint, user):
    qs = complaint.comments.select_related("author")
    role = get_role(user)
    if role == ADMIN:
        return qs
    qs = qs.filter(is_hidden=False)
    return qs if role == OFFICER else qs.filter(is_internal=False)
