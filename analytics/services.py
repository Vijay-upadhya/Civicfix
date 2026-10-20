"""Real metrics computed from the database (no hard-coded numbers)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from accounts.permissions import ADMIN, OFFICER, get_department, get_role
from complaints.models import OPEN_STATUSES, Complaint, Status
from departments.models import Department

S = Status


def scoped_queryset(user, params=None):
    """Complaints the user may analyse, narrowed by optional filters."""
    params = params or {}
    qs = Complaint.objects.exclude(status=S.DRAFT)
    role = get_role(user)
    if role == OFFICER:
        dept = get_department(user)
        qs = qs.filter(department=dept) if dept else qs.none()
    for key, field in (("category", "category_id"), ("department", "department_id"), ("status", "status"),
                       ("priority", "priority_level"), ("ward", "ward__iexact")):
        if params.get(key):
            qs = qs.filter(**{field if "__" in field else field: params[key]})
    if params.get("date_from"):
        qs = qs.filter(created_at__date__gte=params["date_from"])
    if params.get("date_to"):
        qs = qs.filter(created_at__date__lte=params["date_to"])
    return qs


def _pct(a, b):
    return round(a / b * 100, 1) if b else 0.0


def calculate_resolution_metrics(qs):
    now = timezone.now()
    total = qs.count()
    closed = qs.filter(status=S.CLOSED).count()
    resolved_ever = qs.filter(resolved_at__isnull=False)
    resolved_count = resolved_ever.count()
    within_sla = resolved_ever.filter(sla_deadline__isnull=False, resolved_at__lte=F("sla_deadline")).count()
    reopened = qs.filter(history__new_status=S.REOPENED).distinct().count()
    merged = qs.filter(status=S.MERGED).count()
    done = qs.filter(Q(closed_at__isnull=False) | Q(resolved_at__isnull=False), submitted_at__isnull=False)
    dur = ExpressionWrapper(F("closed_at") - F("submitted_at"), output_field=DurationField())
    avg = qs.filter(closed_at__isnull=False, submitted_at__isnull=False).annotate(d=dur).aggregate(a=Avg("d"))["a"]
    return {
        "total_complaints": total,
        "open_complaints": qs.filter(status__in=OPEN_STATUSES).count(),
        "resolved_complaints": qs.filter(status__in=[S.RESOLVED, S.CLOSED]).count(),
        "closed_complaints": closed,
        "resolution_rate": _pct(closed, total),
        "average_resolution_hours": round(avg.total_seconds() / 3600, 1) if avg else None,
        "overdue_complaints": qs.filter(status__in=OPEN_STATUSES, sla_deadline__lt=now).count(),
        "sla_compliance": _pct(within_sla, resolved_count),
        "reopen_rate": _pct(reopened, resolved_count),
        "reopened_complaints": reopened,
        "complaints_today": qs.filter(created_at__date=timezone.localdate()).count(),
        "duplicate_reduction": {"total_complaints": total, "unique_issue_groups": total - merged,
                                "merged_duplicates": merged, "estimated_reduction_pct": _pct(merged, total)},
        "status_counts": dict(qs.values_list("status").annotate(n=Count("id")).order_by()),
    }


def overview(user, params=None):
    qs = scoped_queryset(user, params)
    data = calculate_resolution_metrics(qs)
    data["prediction_accuracy"] = prediction_accuracy(qs)
    if get_role(user) == ADMIN:
        data["total_users"] = get_user_model().objects.count()
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    data["resolved_this_month"] = qs.filter(resolved_at__gte=month_start).count()
    data["new_complaints"] = qs.filter(status__in=[S.SUBMITTED, S.UNDER_REVIEW]).count()
    data["assigned_to_me"] = qs.filter(assigned_officer=user, status__in=OPEN_STATUSES).count()
    data["in_progress"] = qs.filter(status=S.IN_PROGRESS).count()
    return data


def by_category(user, params=None):
    qs = scoped_queryset(user, params)
    rows = (qs.values("category__id", "category__name").annotate(
        total=Count("id"), resolved=Count("id", filter=Q(status__in=[S.RESOLVED, S.CLOSED])),
        open=Count("id", filter=Q(status__in=OPEN_STATUSES))).order_by("-total"))
    return [{"category_id": r["category__id"], "category": r["category__name"] or "Unclassified",
             "total": r["total"], "resolved": r["resolved"], "open": r["open"]} for r in rows]


def by_ward(user, params=None):
    from django.db.models import Avg as A
    qs = scoped_queryset(user, params).exclude(ward="")
    rows = qs.values("ward").annotate(total=Count("id"), open=Count("id", filter=Q(status__in=OPEN_STATUSES)),
                                      avg_priority=A("priority_score"), lat=A("latitude"), lng=A("longitude")).order_by("-total")
    return [{"ward": r["ward"], "total": r["total"], "open": r["open"], "avg_priority": round(r["avg_priority"] or 0, 1),
             "latitude": r["lat"], "longitude": r["lng"]} for r in rows]


def by_department(user, params=None):
    qs = scoped_queryset(user, params)
    now = timezone.now()
    rows = qs.values("department__id", "department__name").annotate(
        total=Count("id"), open=Count("id", filter=Q(status__in=OPEN_STATUSES)),
        resolved=Count("id", filter=Q(status__in=[S.RESOLVED, S.CLOSED])),
        overdue=Count("id", filter=Q(status__in=OPEN_STATUSES, sla_deadline__lt=now)),
        on_time=Count("id", filter=Q(resolved_at__isnull=False, resolved_at__lte=F("sla_deadline"))),
        resolved_ever=Count("id", filter=Q(resolved_at__isnull=False))).order_by("-total")
    return [{"department_id": r["department__id"], "department": r["department__name"], "total": r["total"], "open": r["open"],
             "resolved": r["resolved"], "overdue": r["overdue"], "sla_compliance": _pct(r["on_time"], r["resolved_ever"])} for r in rows]


def resolution_time(user, params=None):
    qs = scoped_queryset(user, params).filter(closed_at__isnull=False, submitted_at__isnull=False)
    dur = ExpressionWrapper(F("closed_at") - F("submitted_at"), output_field=DurationField())
    cats = qs.annotate(d=dur).values("category__name").annotate(avg=Avg("d"), n=Count("id")).order_by("category__name")
    since = timezone.now() - timedelta(days=30)
    daily = (scoped_queryset(user, params).filter(closed_at__gte=since).annotate(day=TruncDate("closed_at"))
             .values("day").annotate(n=Count("id")).order_by("day"))
    return {"by_category": [{"category": c["category__name"], "average_hours": round(c["avg"].total_seconds() / 3600, 1),
                              "count": c["n"]} for c in cats],
            "closed_per_day": [{"date": d["day"].isoformat(), "count": d["n"]} for d in daily]}


def overdue(user, params=None):
    now = timezone.now()
    qs = scoped_queryset(user, params).filter(status__in=OPEN_STATUSES, sla_deadline__lt=now).select_related("department", "category").order_by("sla_deadline")[:100]
    return [{"id": c.id, "complaint_number": c.complaint_number, "title": c.title, "department": c.department.name if c.department else None,
             "overdue_hours": int((now - c.sla_deadline).total_seconds() // 3600), "priority": c.priority_level} for c in qs]


def sla_compliance(user, params=None):
    return {"overall": calculate_resolution_metrics(scoped_queryset(user, params))["sla_compliance"],
            "by_department": [{"department": d["department"], "sla_compliance": d["sla_compliance"]} for d in by_department(user, params)]}


def prediction_accuracy(qs):
    scored = qs.filter(predicted_category__isnull=False, category__isnull=False)
    total = scored.count()
    correct = scored.filter(predicted_category=F("category")).count()
    return {"evaluated": total, "correct": correct, "accuracy": _pct(correct, total),
            "corrected_by_admin": scored.filter(category_corrected=True).count(),
            "average_confidence": round(scored.aggregate(a=Avg("prediction_confidence"))["a"] or 0, 2)}


def department_analytics(dept):
    qs = Complaint.objects.filter(department=dept).exclude(status=S.DRAFT)
    data = calculate_resolution_metrics(qs)
    workload = (get_user_model().objects.filter(profile__department=dept, profile__role=OFFICER)
                .annotate(open_count=Count("assigned_complaints", filter=Q(assigned_complaints__status__in=OPEN_STATUSES)))
                .values("id", "first_name", "last_name", "email", "open_count"))
    data["department"] = dept.name
    data["workload"] = [{"officer_id": w["id"], "name": f"{w['first_name']} {w['last_name']}".strip() or w["email"], "open": w["open_count"]} for w in workload]
    data["unassigned_open"] = qs.filter(assigned_officer__isnull=True, status__in=OPEN_STATUSES).count()
    return data


def public_stats():
    """Landing-page numbers. Labelled as demo data when DEMO_MODE is on."""
    from django.conf import settings
    qs = Complaint.objects.exclude(status__in=[S.DRAFT, S.REJECTED])
    markers = [] if not settings.PUBLIC_MAP_MARKERS else qs.exclude(status=S.MERGED).values("id", "complaint_number", "title", "latitude", "longitude", "priority_level", "status", "ward")[:300]
    return {"demo": settings.DEMO_MODE, "markers_public": settings.PUBLIC_MAP_MARKERS, "issues_reported": qs.count(),
            "issues_resolved": qs.filter(status__in=[S.RESOLVED, S.CLOSED]).count(),
            "active_departments": Department.objects.filter(active=True).count(), "markers": list(markers)}
