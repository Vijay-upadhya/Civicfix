import django_filters as df
from django.db.models import Q

from . import services
from .models import Complaint


class ComplaintFilter(df.FilterSet):
    search = df.CharFilter(method="filter_search")
    category = df.NumberFilter(field_name="category_id")
    department = df.NumberFilter(field_name="department_id")
    status = df.CharFilter(field_name="status")
    priority = df.CharFilter(field_name="priority_level")
    ward = df.CharFilter(field_name="ward", lookup_expr="iexact")
    date_from = df.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to = df.DateFilter(field_name="created_at", lookup_expr="date__lte")
    mine = df.BooleanFilter(method="filter_mine")
    overdue = df.BooleanFilter(method="filter_overdue")
    near_lat = df.NumberFilter(method="filter_near")
    near_lng = df.NumberFilter(method="filter_noop")
    radius = df.NumberFilter(method="filter_noop")

    class Meta:
        model = Complaint
        fields = []

    def filter_search(self, qs, name, value):
        return qs.filter(Q(title__icontains=value) | Q(description__icontains=value) | Q(complaint_number__icontains=value)
                         | Q(landmark__icontains=value) | Q(address__icontains=value))

    def filter_mine(self, qs, name, value):
        return qs.filter(created_by=self.request.user) if value else qs

    def filter_overdue(self, qs, name, value):
        from django.utils import timezone
        from .models import OPEN_STATUSES
        overdue = qs.filter(status__in=OPEN_STATUSES, sla_deadline__lt=timezone.now())
        return overdue if value else qs.exclude(pk__in=overdue.values("pk"))

    def filter_noop(self, qs, name, value):
        return qs

    def filter_near(self, qs, name, value):
        data = self.data
        try:
            lat, lng, radius = float(value), float(data.get("near_lng")), float(data.get("radius", 500))
        except (TypeError, ValueError):
            return qs
        s, n, w, e = services.bounding_box(lat, lng, radius)
        return qs.filter(latitude__range=(s, n), longitude__range=(w, e))
