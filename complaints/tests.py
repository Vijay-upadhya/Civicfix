import io
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from departments.reference import ensure_reference_data
from . import services
from .models import Complaint, Status, Upvote

User = get_user_model()
S = Status
LAT, LNG = 12.9166, 77.6101


def png_bytes(fmt="PNG", size=(20, 20)):
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, fmt)
    return buf.getvalue()


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.depts, cls.cats = ensure_reference_data()
        mk = lambda e, role="citizen", dept=None: _user(e, role, dept)
        cls.citizen, cls.citizen2 = mk("c1@example.com"), mk("c2@example.com")
        cls.officer = mk("o1@example.com", "officer", cls.depts["Electrical Services"])
        cls.other_officer = mk("o2@example.com", "officer", cls.depts["Roads Department"])
        cls.admin = mk("a@example.com", "admin")

    def client_for(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def payload(self, **kw):
        d = dict(title="Broken streetlight near metro", description="The streetlight has not been working for three nights.",
                 category=self.cats["streetlight"].id, latitude=LAT, longitude=LNG, ward="Ward 2", safety_risk=False, affected_people=5)
        d.update(kw)
        return d

    def draft(self, user=None, **kw):
        r = self.client_for(user or self.citizen).post("/api/complaints/", self.payload(**kw), format="json")
        assert r.status_code == 201, r.data
        return r.data["id"]

    def submitted(self, **kw):
        cid = self.draft(**kw)
        r = self.client_for(self.citizen).post(f"/api/complaints/{cid}/submit/")
        assert r.status_code == 200, r.data
        return Complaint.objects.get(pk=cid)


def _user(email, role, dept=None):
    u = User.objects.create_user(username=email, email=email, password="DemoPassword123")
    u.profile.role, u.profile.department = role, dept
    u.profile.save()
    return u


class ModelAndServiceTests(Base):
    def test_default_status_is_draft_and_number_assigned_on_submit(self):
        c = Complaint.objects.get(pk=self.draft())
        self.assertEqual(c.status, S.DRAFT)
        self.assertIsNone(c.complaint_number)
        c = self.submitted()
        self.assertRegex(c.complaint_number, r"^CF-\d{4}-\d{6}$")

    def test_unique_upvote_constraint(self):
        c = self.submitted()
        Upvote.objects.create(complaint=c, user=self.citizen2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Upvote.objects.create(complaint=c, user=self.citizen2)

    def test_priority_boundaries(self):
        self.assertEqual(services.priority_level_for(29), "LOW")
        self.assertEqual(services.priority_level_for(30), "MEDIUM")
        self.assertEqual(services.priority_level_for(59), "MEDIUM")
        self.assertEqual(services.priority_level_for(60), "HIGH")
        self.assertEqual(services.priority_level_for(79), "HIGH")
        self.assertEqual(services.priority_level_for(80), "CRITICAL")
        r = services.calculate_priority(severity="CRITICAL", safety_risk=True, affected_people=500, upvotes=99, duplicates=9, days_unresolved=30)
        self.assertEqual(r["score"], 100)
        self.assertTrue(r["reasons"])

    def test_priority_explains_reasons(self):
        r = services.calculate_priority(severity="MEDIUM", safety_risk=True, upvotes=22, days_unresolved=5, location_text="near the main road")
        self.assertIn("Marked as a safety risk (+20)", r["reasons"])
        self.assertTrue(any("22 upvotes" in x for x in r["reasons"]))
        self.assertEqual(r["level"], "HIGH")

    def test_sla_deadline_uses_category_hours_and_safety_cap(self):
        c = Complaint(category=self.cats["streetlight"], safety_risk=False)
        start = timezone.now()
        self.assertEqual(services.calculate_sla_deadline(c, start), start + timedelta(hours=72))
        c.safety_risk = True
        self.assertEqual(services.calculate_sla_deadline(c, start), start + timedelta(hours=24))
        c = Complaint(category=self.cats["pothole"])
        self.assertEqual(services.calculate_sla_deadline(c, start), start + timedelta(hours=168))

    def test_priority_override_preserves_original(self):
        c = self.submitted()
        original = c.priority_score
        services.override_priority(c, 95, "Near a hospital", self.admin)
        c.refresh_from_db()
        self.assertEqual((c.priority_original_score, c.priority_score, c.priority_level), (original, 95, "CRITICAL"))
        with self.assertRaises(ValueError):
            services.override_priority(c, 10, "", self.admin)


class DuplicateTests(Base):
    def test_nearby_similar_complaint_found_and_far_one_ignored(self):
        near = self.submitted()
        found = services.find_possible_duplicates(latitude=LAT + 0.0003, longitude=LNG, text="Street lamp not working near metro", category=self.cats["streetlight"])
        self.assertEqual([f["complaint"].pk for f in found], [near.pk])
        self.assertGreaterEqual(found[0]["similarity"], 40)
        far = services.find_possible_duplicates(latitude=LAT + 0.02, longitude=LNG, text="Street lamp not working near metro", category=self.cats["streetlight"])
        self.assertEqual(far, [])

    def test_resolved_complaints_are_not_duplicates(self):
        c = self.submitted()
        Complaint.objects.filter(pk=c.pk).update(status=S.CLOSED)
        self.assertEqual(services.find_possible_duplicates(latitude=LAT, longitude=LNG, text="streetlight", category=self.cats["streetlight"]), [])

    def test_merge_marks_children_and_audits(self):
        parent, child = self.submitted(), self.submitted(title="Street lamp not working near metro")
        merged = services.merge_duplicate_complaints(parent, [child], self.admin, "same issue")
        child.refresh_from_db()
        self.assertEqual(merged, [child.pk])
        self.assertEqual((child.status, child.parent_complaint_id, child.is_duplicate), (S.MERGED, parent.pk, True))
        self.assertTrue(child.history.filter(new_status=S.MERGED).exists())
        self.assertTrue(child.history.filter(new_status=S.ASSIGNED).exists())  # history preserved
        from .models import AuditLog
        self.assertTrue(AuditLog.objects.filter(action="COMPLAINT_MERGE", entity_id=parent.pk).exists())


class WorkflowTests(Base):
    def test_full_lifecycle_and_reopen(self):
        c = self.submitted()
        self.assertEqual(c.status, S.ASSIGNED)
        self.assertEqual(c.department.name, "Electrical Services")
        self.assertEqual(c.assigned_officer, self.officer)
        self.assertEqual([h.new_status for h in c.history.all()], [S.SUBMITTED, S.UNDER_REVIEW, S.ASSIGNED])
        off, cit = self.client_for(self.officer), self.client_for(self.citizen)
        self.assertEqual(off.patch(f"/api/complaints/{c.id}/status/", {"status": "IN_PROGRESS"}, format="json").status_code, 200)
        self.assertEqual(off.post(f"/api/complaints/{c.id}/resolve/", {}, format="json").status_code, 400)  # needs a comment
        self.assertEqual(off.post(f"/api/complaints/{c.id}/resolve/", {"comment": "Bulb replaced"}, format="json").status_code, 200)
        r = cit.post(f"/api/complaints/{c.id}/reopen/", {"comment": "Still dark"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "REOPENED")
        self.assertEqual(off.patch(f"/api/complaints/{c.id}/status/", {"status": "ASSIGNED", "comment": "again"}, format="json").status_code, 200)
        off.patch(f"/api/complaints/{c.id}/status/", {"status": "IN_PROGRESS"}, format="json")
        off.post(f"/api/complaints/{c.id}/resolve/", {"comment": "Fixed properly"}, format="json")
        self.assertEqual(cit.post(f"/api/complaints/{c.id}/confirm/").data["status"], "CLOSED")
        c.refresh_from_db()
        self.assertIsNotNone(c.closed_at)

    def test_invalid_transitions_rejected(self):
        c = self.submitted()
        with self.assertRaises(services.TransitionError):
            services.create_status_event(c, S.CLOSED, self.admin)
        r = self.client_for(self.citizen).patch(f"/api/complaints/{c.id}/status/", {"status": "RESOLVED", "comment": "x"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_waiting_for_info_and_citizen_reply(self):
        c = self.submitted()
        off = self.client_for(self.officer)
        off.patch(f"/api/complaints/{c.id}/status/", {"status": "IN_PROGRESS"}, format="json")
        self.assertEqual(off.post(f"/api/complaints/{c.id}/request-info/", {"comment": "Which pole?"}, format="json").status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.status, S.WAITING_INFO)
        self.client_for(self.citizen).post(f"/api/complaints/{c.id}/comment/", {"text": "Pole 14"}, format="json")
        c.refresh_from_db()
        self.assertEqual(c.status, S.IN_PROGRESS)

    def test_admin_can_reject_and_citizen_cannot(self):
        c = self.submitted()
        self.assertEqual(self.client_for(self.citizen).patch(f"/api/complaints/{c.id}/status/", {"status": "REJECTED", "comment": "x"}, format="json").status_code, 403)
        self.assertEqual(self.client_for(self.admin).patch(f"/api/complaints/{c.id}/status/", {"status": "REJECTED", "comment": "Spam"}, format="json").status_code, 200)

    def test_low_confidence_unsure_complaint_goes_to_general_review(self):
        cid = self.draft(category=None, title="Something odd happening here", description="Please check this thing at some point soon, thanks.")
        r = self.client_for(self.citizen).post(f"/api/complaints/{cid}/submit/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Complaint.objects.get(pk=cid).department.name, "General Review Department")

    def test_unsure_category_is_classified_from_text(self):
        cid = self.draft(category=None, title="Huge pothole on the road", description="There is a deep pothole near the bus stop, bikes skid here.")
        self.client_for(self.citizen).post(f"/api/complaints/{cid}/submit/")
        c = Complaint.objects.get(pk=cid)
        self.assertEqual(c.category.slug, "pothole")
        self.assertEqual(c.department.name, "Roads Department")
        self.assertIsNotNone(c.prediction_confidence)


class ApiAndSecurityTests(Base):
    def test_unauthenticated_cannot_create_or_list(self):
        c = APIClient()
        self.assertEqual(c.post("/api/complaints/", self.payload(), format="json").status_code, 401)
        self.assertEqual(c.get("/api/complaints/").status_code, 401)

    def test_validation_rules(self):
        cit = self.client_for(self.citizen)
        self.assertEqual(cit.post("/api/complaints/", self.payload(title="Hi"), format="json").status_code, 400)
        self.assertEqual(cit.post("/api/complaints/", self.payload(description="too short"), format="json").status_code, 400)
        self.assertEqual(cit.post("/api/complaints/", self.payload(affected_people=-2), format="json").status_code, 400)
        self.assertEqual(cit.post("/api/complaints/", self.payload(description="a" * 30), format="json").status_code, 400)

    def test_citizen_cannot_see_another_citizens_draft(self):
        cid = self.draft()
        self.assertEqual(self.client_for(self.citizen2).get(f"/api/complaints/{cid}/").status_code, 404)
        self.assertEqual(self.client_for(self.citizen).get(f"/api/complaints/{cid}/").status_code, 200)

    def test_citizen_cannot_change_priority_status_or_department(self):
        cid = self.draft()
        cit = self.client_for(self.citizen)
        for body in ({"priority_score": 99}, {"status": "CLOSED"}, {"department": self.depts["Roads Department"].id}):
            self.assertEqual(cit.patch(f"/api/complaints/{cid}/", body, format="json").status_code, 403, body)
        self.assertEqual(cit.patch(f"/api/complaints/{cid}/", {"title": "Updated title here"}, format="json").status_code, 200)

    def test_citizen_cannot_edit_submitted_or_others_complaint(self):
        c = self.submitted()
        self.assertEqual(self.client_for(self.citizen).patch(f"/api/complaints/{c.id}/", {"title": "New title"}, format="json").status_code, 403)
        self.assertEqual(self.client_for(self.citizen2).patch(f"/api/complaints/{c.id}/", {"title": "New title"}, format="json").status_code, 403)

    def test_admin_changes_category_and_priority(self):
        c = self.submitted()
        adm = self.client_for(self.admin)
        r = adm.patch(f"/api/complaints/{c.id}/", {"category": self.cats["pothole"].id}, format="json")
        self.assertEqual(r.status_code, 200)
        c.refresh_from_db()
        self.assertTrue(c.category_corrected)
        self.assertEqual(c.department.name, "Roads Department")
        self.assertEqual(adm.patch(f"/api/complaints/{c.id}/", {"priority_score": 90}, format="json").status_code, 400)  # reason required
        self.assertEqual(adm.patch(f"/api/complaints/{c.id}/", {"priority_score": 90, "priority_override_reason": "Hospital"}, format="json").status_code, 200)

    def test_officer_scope_and_internal_notes(self):
        c = self.submitted()
        off, other = self.client_for(self.officer), self.client_for(self.other_officer)
        self.assertEqual(off.post(f"/api/complaints/{c.id}/comment/", {"text": "Crew booked", "is_internal": True}, format="json").status_code, 201)
        self.assertEqual(other.get(f"/api/complaints/{c.id}/").status_code, 404)  # other department
        self.assertEqual(other.patch(f"/api/complaints/{c.id}/status/", {"status": "IN_PROGRESS"}, format="json").status_code, 404)
        cit = self.client_for(self.citizen).get(f"/api/complaints/{c.id}/").data
        self.assertFalse(any(m["is_internal"] for m in cit["comments"]))
        self.assertEqual(self.client_for(self.citizen).post(f"/api/complaints/{c.id}/comment/", {"text": "x", "is_internal": True}, format="json").status_code, 403)
        self.assertTrue(any(m["is_internal"] for m in off.get(f"/api/complaints/{c.id}/").data["comments"]))

    def test_duplicate_upvote_blocked_and_count_updates(self):
        c = self.submitted()
        cl = self.client_for(self.citizen2)
        self.assertEqual(cl.post(f"/api/complaints/{c.id}/upvote/").status_code, 200)
        self.assertEqual(cl.post(f"/api/complaints/{c.id}/upvote/").status_code, 400)
        c.refresh_from_db()
        self.assertEqual(c.upvotes_count, 1)
        self.assertEqual(cl.delete(f"/api/complaints/{c.id}/upvote/").data["upvotes"], 0)

    def test_admin_only_actions(self):
        c = self.submitted()
        for user in (self.citizen, self.officer):
            cl = self.client_for(user)
            self.assertEqual(cl.post(f"/api/complaints/{c.id}/merge/", {"duplicate_ids": [c.id]}, format="json").status_code, 403)
            self.assertEqual(cl.post(f"/api/complaints/{c.id}/assign/", {}, format="json").status_code, 403)
            self.assertEqual(cl.get("/api/users/").status_code, 403)
            self.assertEqual(cl.get("/api/audit-logs/").status_code, 403)
        self.assertEqual(self.client_for(self.admin).get("/api/users/").status_code, 200)

    def test_delete_rules(self):
        cid = self.draft()
        self.assertEqual(self.client_for(self.citizen2).delete(f"/api/complaints/{cid}/").status_code, 404)
        self.assertEqual(self.client_for(self.citizen).delete(f"/api/complaints/{cid}/").status_code, 204)
        c = self.submitted()
        self.assertEqual(self.client_for(self.citizen).delete(f"/api/complaints/{c.id}/").status_code, 403)
        self.assertEqual(self.client_for(self.admin).delete(f"/api/complaints/{c.id}/").status_code, 204)

    def test_filtering_pagination_and_search(self):
        for i in range(3):
            self.submitted(title=f"Streetlight issue number {i}")
        cl = self.client_for(self.citizen)
        r = cl.get("/api/complaints/?page_size=2")
        self.assertEqual((r.data["count"], len(r.data["results"])), (3, 2))
        self.assertEqual(cl.get("/api/complaints/?search=number 1").data["count"], 1)
        self.assertEqual(cl.get(f"/api/complaints/?category={self.cats['pothole'].id}").data["count"], 0)
        self.assertEqual(cl.get("/api/complaints/?mine=true").data["count"], 3)
        self.assertEqual(self.client_for(self.citizen2).get("/api/complaints/?mine=true").data["count"], 0)

    def test_notifications_created_and_readable(self):
        c = self.submitted()
        cl = self.client_for(self.citizen)
        data = cl.get("/api/notifications/").data
        self.assertTrue(data["count"] >= 1)
        nid = data["results"][0]["id"]
        self.assertEqual(self.client_for(self.citizen2).patch(f"/api/notifications/{nid}/read/").status_code, 404)
        self.assertTrue(cl.patch(f"/api/notifications/{nid}/read/").data["is_read"])
        self.assertEqual(cl.post("/api/notifications/mark-all-read/").status_code, 200)
        self.assertGreaterEqual(self.client_for(self.officer).get("/api/notifications/").data["count"], 1)

    def test_role_change_is_audited_and_validated(self):
        adm = self.client_for(self.admin)
        r = adm.patch(f"/api/users/{self.citizen.id}/role/", {"role": "officer"}, format="json")
        self.assertEqual(r.status_code, 400)  # needs department
        r = adm.patch(f"/api/users/{self.citizen.id}/role/", {"role": "officer", "department": self.depts["Roads Department"].id}, format="json")
        self.assertEqual(r.status_code, 200)
        from .models import AuditLog
        self.assertTrue(AuditLog.objects.filter(action="USER_ROLE_CHANGE").exists())
        self.assertEqual(adm.patch(f"/api/users/{self.admin.id}/role/", {"role": "citizen"}, format="json").status_code, 400)

    def test_comment_hiding_and_internal_visibility_for_admin(self):
        c = self.submitted()
        cm = self.client_for(self.citizen).post(f"/api/complaints/{c.id}/comment/", {"text": "rude text"}, format="json").data
        self.assertEqual(self.client_for(self.citizen2).patch(f"/api/comments/{cm['id']}/hide/").status_code, 403)
        self.assertEqual(self.client_for(self.admin).patch(f"/api/comments/{cm['id']}/hide/", {"reason": "abuse"}, format="json").status_code, 200)
        self.assertEqual(len(self.client_for(self.citizen2).get(f"/api/complaints/{c.id}/").data["comments"]), 0)


class UploadTests(Base):
    def upload(self, cid, name, content, user=None, **extra):
        f = SimpleUploadedFile(name, content)
        return self.client_for(user or self.citizen).post(f"/api/complaints/{cid}/images/", {"image": f, **extra}, format="multipart")

    def setUp(self):
        import tempfile
        self._tmp = tempfile.mkdtemp()
        self._ctx = override_settings(MEDIA_ROOT=__import__("pathlib").Path(self._tmp))
        self._ctx.enable()
        self.addCleanup(self._ctx.disable)

    def test_valid_png_accepted_with_safe_filename(self):
        cid = self.draft()
        r = self.upload(cid, "../../evil name.png", png_bytes())
        self.assertEqual(r.status_code, 201, r.data)
        self.assertNotIn("evil", r.data["url"])
        self.assertRegex(r.data["url"], r"^/media/complaints/\d{4}/\d{2}/[0-9a-f]{32}\.png$")

    def test_invalid_types_rejected(self):
        cid = self.draft()
        self.assertEqual(self.upload(cid, "x.exe", b"MZ....").status_code, 400)
        self.assertEqual(self.upload(cid, "x.gif", png_bytes("GIF")).status_code, 400)
        self.assertEqual(self.upload(cid, "fake.png", b"<?php echo 1; ?>").status_code, 400)  # content check, not extension
        self.assertEqual(self.upload(cid, "x.jpg", png_bytes("PNG")).status_code, 201)  # real image bytes ok
        self.assertEqual(self.upload(cid, "x.png", png_bytes("WEBP")).status_code, 400)

    def test_oversized_and_limit_rejected(self):
        cid = self.draft()
        big = png_bytes() + b"0" * (5 * 1024 * 1024 + 10)
        self.assertEqual(self.upload(cid, "big.png", big).status_code, 400)
        for _ in range(3):
            self.assertEqual(self.upload(cid, "a.png", png_bytes()).status_code, 201)
        self.assertEqual(self.upload(cid, "a.png", png_bytes()).status_code, 400)

    def test_permissions(self):
        cid = self.draft()
        self.assertEqual(self.upload(cid, "a.png", png_bytes(), user=self.citizen2).status_code, 404)
        c = self.submitted()
        self.assertEqual(self.upload(c.id, "a.png", png_bytes()).status_code, 403)  # citizens can't add after submit
        self.assertEqual(self.upload(c.id, "a.png", png_bytes(), user=self.officer, is_resolution_evidence="true").status_code, 201)
        self.assertEqual(self.upload(c.id, "a.png", png_bytes(), user=self.other_officer, is_resolution_evidence="true").status_code, 404)
        self.assertEqual(APIClient().post(f"/api/complaints/{c.id}/images/", {}, format="multipart").status_code, 401)

    def test_media_requires_login_and_visibility(self):
        cid = self.draft()
        url = self.upload(cid, "a.png", png_bytes()).data["url"]
        from django.test import Client
        self.assertEqual(Client().get(url).status_code, 302)  # redirect to login
        mine, other = Client(), Client()
        mine.force_login(self.citizen)
        other.force_login(self.citizen2)
        self.assertEqual(mine.get(url).status_code, 200)
        self.assertEqual(other.get(url).status_code, 404)  # private draft


class IntelligenceApiTests(Base):
    def test_classify_endpoint(self):
        r = self.client_for(self.citizen).post("/api/intelligence/classify/", {"title": "Garbage overflowing", "description": "Waste not collected near the market"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["category"]["slug"], "garbage")
        self.assertEqual(r.data["department"]["name"], "Sanitation Department")
        self.assertIn("explanation", r.data)

    def test_check_duplicates_endpoint(self):
        self.submitted()
        r = self.client_for(self.citizen2).post("/api/intelligence/check-duplicates/", {"latitude": LAT, "longitude": LNG, "title": "Street lamp not working", "description": "dark at night", "category": self.cats["streetlight"].id}, format="json")
        self.assertEqual(r.data["count"], 1)

    def test_calculate_priority_endpoint(self):
        r = self.client_for(self.citizen).post("/api/intelligence/calculate-priority/", {"severity": "HIGH", "safety_risk": True, "affected_people": 30}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data["score"], r.data["level"]), (51, "MEDIUM"))
