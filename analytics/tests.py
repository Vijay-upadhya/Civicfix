from complaints.tests import Base
from complaints.models import Complaint, Status
from django.utils import timezone
from datetime import timedelta
from . import services


class AnalyticsTests(Base):
    def test_metrics_computed_from_data(self):
        a, b = self.submitted(), self.submitted(title="Another streetlight problem")
        now = timezone.now()
        Complaint.objects.filter(pk=a.pk).update(status=Status.CLOSED, submitted_at=now - timedelta(hours=10), resolved_at=now - timedelta(hours=2),
                                                 closed_at=now, sla_deadline=now)
        m = services.calculate_resolution_metrics(Complaint.objects.all())
        self.assertEqual((m["total_complaints"], m["closed_complaints"], m["resolution_rate"]), (2, 1, 50.0))
        self.assertEqual(m["average_resolution_hours"], 10.0)
        self.assertEqual(m["sla_compliance"], 100.0)

    def test_endpoints_permissions_and_scope(self):
        self.submitted()
        self.assertEqual(self.client_for(self.citizen).get("/api/analytics/overview/").status_code, 403)
        self.assertEqual(self.client_for(self.admin).get("/api/analytics/overview/").data["total_complaints"], 1)
        self.assertEqual(self.client_for(self.officer).get("/api/analytics/overview/").data["total_complaints"], 1)
        self.assertEqual(self.client_for(self.other_officer).get("/api/analytics/overview/").data["total_complaints"], 0)
        for p in ("by-category", "by-ward", "by-department", "resolution-time", "overdue", "sla-compliance", "prediction-accuracy"):
            self.assertEqual(self.client_for(self.admin).get(f"/api/analytics/{p}/").status_code, 200, p)

    def test_department_analytics_scope(self):
        self.submitted()
        d = self.depts["Electrical Services"].id
        self.assertEqual(self.client_for(self.officer).get(f"/api/departments/{d}/analytics/").status_code, 200)
        self.assertEqual(self.client_for(self.other_officer).get(f"/api/departments/{d}/analytics/").status_code, 403)

    def test_public_stats_is_anonymous_and_hides_drafts(self):
        self.draft()
        self.submitted()
        from rest_framework.test import APIClient
        r = APIClient().get("/api/public/stats/")
        self.assertEqual((r.status_code, r.data["issues_reported"], len(r.data["markers"])), (200, 1, 1))


from django.test import override_settings


class PublicMapFlagTests(Base):
    def test_markers_hidden_when_flag_off(self):
        self.submitted()
        from rest_framework.test import APIClient
        with override_settings(PUBLIC_MAP_MARKERS=False):
            r = APIClient().get("/api/public/stats/")
        self.assertEqual((r.data["markers"], r.data["markers_public"]), ([], False))
        self.assertEqual(r.data["issues_reported"], 1)
