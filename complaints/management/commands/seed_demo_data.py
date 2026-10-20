import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import PrivacyPolicyAcceptance
from complaints.models import Comment, Complaint, ComplaintStatusHistory, Status, Upvote
from complaints.services import calculate_priority, priority_level_for
from departments.reference import ensure_reference_data
from notifications.models import Notification

S = Status
User = get_user_model()
PASSWORD = "DemoPassword123"
WARDS = {"Ward 1 - Indiranagar": (12.9719, 77.6412), "Ward 2 - BTM Layout": (12.9166, 77.6101), "Ward 3 - Jayanagar": (12.9250, 77.5938),
         "Ward 4 - Koramangala": (12.9352, 77.6245), "Ward 5 - Whitefield": (12.9698, 77.7500), "Ward 6 - Malleshwaram": (13.0035, 77.5710)}
TEXTS = {
    "pothole": ["Large pothole near the metro entrance, two-wheelers skid at night", "Deep road hole beside the bus stop after the rains"],
    "garbage": ["Garbage overflowing beside the market for three days", "Bin overflow near the park and a bad smell"],
    "streetlight": ["Street lamp is not working near 5th Main Road", "Broken streetlight, the whole lane is dark at night"],
    "water": ["Water leaking from the main pipe near the school", "Pipe burst and water flowing on the road"],
    "drain": ["Drain is blocked and sewage is overflowing on the road", "Open manhole next to the bus stop"],
    "footpath": ["Footpath tiles are broken and unsafe for senior citizens", "Damaged pavement outside the hospital"],
    "traffic": ["Traffic signal not working at the junction, long jams", "Signal timer stuck on red near the market"],
    "animal": ["Stray dogs chasing people in the evening", "Stray cattle sitting on the main road"],
    "dumping": ["Illegal dumping of construction debris in the empty plot", "Trucks dump waste on the roadside every night"],
    "safety": ["Exposed electric wire hanging low near the children's play area", "Fallen tree branch is blocking the lane and is dangerous"],
    "park": ["Park bench and swings are broken in the community park", "Garden fence collapsed and playground is unsafe"],
    "other": ["Request for a public toilet near the bus stand", "Loud late-night speakers near the residential lane"],
}


class Command(BaseCommand):
    help = "Seed clearly labelled DEMO data (synthetic only). Safe to re-run: skips if demo data exists unless --reset."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete existing demo complaints and re-seed.")

    @transaction.atomic
    def handle(self, *args, **opts):
        random.seed(2026)
        depts, cats = ensure_reference_data()
        if User.objects.filter(email="citizen@example.com").exists():
            if not opts["reset"]:
                self.stdout.write("Demo data already present. Use --reset to rebuild.")
                return
            Complaint.objects.all().delete()
        admin = self._user("admin@example.com", "Demo", "Admin", role="admin", superuser=True)
        citizens = [self._user("citizen@example.com", "Demo", "Citizen")] + [
            self._user(f"citizen{i}@example.com", f"Citizen{i}", "Demo", ward=random.choice(list(WARDS))) for i in range(2, 21)]
        officer_depts = ["Roads Department", "Sanitation Department", "Electrical Services", "Water Services", "Drainage Department"]
        officers = [self._user("officer@example.com" if i == 0 else f"officer{i + 1}@example.com", "Demo", f"Officer {i + 1}",
                               role="officer", department=depts[d]) for i, d in enumerate(officer_depts)]
        for u in [admin] + citizens + officers:
            PrivacyPolicyAcceptance.objects.get_or_create(user=u, policy_version="2026-10")
        now = timezone.now()
        slugs = [s for s in TEXTS if s != "other"] * 4 + ["other"] * 3
        made = []
        for i in range(100):
            slug = slugs[i % len(slugs)]
            made.append(self._complaint(i, slug, cats, depts, citizens, officers, now))
        self._finalise(made, citizens, now)
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {Complaint.objects.count()} complaints. Demo logins (password {PASSWORD}): "
            "citizen@example.com, officer@example.com, admin@example.com. DEMO DATA ONLY."))

    def _user(self, email, first, last, role="citizen", department=None, ward="", superuser=False):
        u, created = User.objects.get_or_create(username=email, defaults=dict(email=email, first_name=first, last_name=last,
                                                                              is_superuser=superuser, is_staff=superuser))
        u.set_password(PASSWORD)
        u.save()
        u.profile.role, u.profile.department, u.profile.ward, u.profile.is_verified = role, department, ward, True
        u.profile.save()
        return u

    def _complaint(self, i, slug, cats, depts, citizens, officers, now):
        cat = cats[slug]
        ward, (lat, lng) = random.choice(list(WARDS.items()))
        text = random.choice(TEXTS[slug])
        safety = slug == "safety" or random.random() < 0.15
        c = Complaint(created_by=random.choice(citizens), title=text.split(",")[0][:90], description=text + ". Reported by a resident (demo data).",
                      category=cat, predicted_category=cat if random.random() < 0.9 else cats["other"],
                      prediction_confidence=round(random.uniform(0.45, 0.95), 2), department=cat.department,
                      latitude=lat + random.uniform(-0.012, 0.012), longitude=lng + random.uniform(-0.012, 0.012),
                      ward=ward, address=f"{ward}, Bengaluru (demo)", landmark=random.choice(["near metro entrance", "near market", "near school", "near 5th Main Road"]),
                      severity=cat.default_severity, safety_risk=safety, affected_people=random.choice([0, 3, 10, 40, 120]))
        c.save()
        return c

    def _history(self, c, steps, start):
        t = start
        prev = ""
        for status, who, comment in steps:
            ComplaintStatusHistory.objects.create(complaint=c, old_status=prev, new_status=status, changed_by=who, comment=comment)
            ComplaintStatusHistory.objects.filter(complaint=c, new_status=status).update(created_at=t)
            prev, t = status, t + timedelta(hours=random.randint(1, 14))
        return t

    def _finalise(self, made, citizens, now):
        random.shuffle(made)
        parents, children = made[:15], made[15:30]
        resolved, overdue, rest = made[30:60], made[60:70], made[70:]
        for c in made:
            officer = User.objects.filter(profile__department=c.department, profile__role="officer").first()
            c.assigned_officer = officer
            c.submitted_at = now - timedelta(days=random.randint(1, 28), hours=random.randint(0, 20))
            c.complaint_number = f"CF-{c.submitted_at:%Y}-{c.pk:06d}"
            c.sla_deadline = c.submitted_at + timedelta(hours=min(c.category.sla_hours, 24) if c.safety_risk else c.category.sla_hours)
            c.assigned_at = c.submitted_at + timedelta(hours=1)
            c.save()
            Complaint.objects.filter(pk=c.pk).update(created_at=c.submitted_at)
            base = [(S.SUBMITTED, c.created_by, "Complaint submitted"), (S.UNDER_REVIEW, None, "Automatic validation and routing"),
                    (S.ASSIGNED, None, f"Routed to {c.department.name}")]
            end = self._history(c, base, c.submitted_at)
            if c in resolved:
                c.status = S.CLOSED if random.random() < 0.7 else S.RESOLVED
                late = random.random() < 0.25
                c.resolved_at = c.sla_deadline + timedelta(hours=random.randint(2, 30)) if late else c.submitted_at + (c.sla_deadline - c.submitted_at) * random.uniform(0.3, 0.9)
                c.resolved_at = min(c.resolved_at, now - timedelta(hours=1))
                steps = [(S.IN_PROGRESS, c.assigned_officer, "Crew dispatched"), (S.RESOLVED, c.assigned_officer, "Work completed")]
                if c.status == S.CLOSED:
                    c.closed_at = c.resolved_at + timedelta(hours=random.randint(2, 40))
                    c.closed_at = min(c.closed_at, now)
                    steps.append((S.CLOSED, c.created_by, "Resolution confirmed"))
                self._history(c, [(S.ASSIGNED, None, "")] + steps, end)
            elif c in overdue:
                c.status = S.IN_PROGRESS
                c.submitted_at = now - timedelta(hours=c.category.sla_hours + random.randint(10, 160))
                c.sla_deadline = c.submitted_at + timedelta(hours=c.category.sla_hours)
                Complaint.objects.filter(pk=c.pk).update(created_at=c.submitted_at)
                self._history(c, [(S.ASSIGNED, None, ""), (S.IN_PROGRESS, c.assigned_officer, "Inspection scheduled")], end)
            elif c in children:
                c.status = S.MERGED
                c.is_duplicate = True
                c.parent_complaint = parents[children.index(c)]
                c.latitude, c.longitude = c.parent_complaint.latitude + 0.0004, c.parent_complaint.longitude
                self._history(c, [(S.ASSIGNED, None, ""), (S.MERGED, None, f"Merged into {c.parent_complaint.display_number if c.parent_complaint.complaint_number else 'parent'}")], end)
            else:
                c.status = random.choice([S.ASSIGNED, S.ASSIGNED, S.IN_PROGRESS, S.IN_PROGRESS, S.WAITING_INFO, S.REOPENED])
                if c.status != S.ASSIGNED:
                    c.submitted_at = now - timedelta(hours=random.randint(2, max(3, int(c.category.sla_hours * 0.8))))
                    c.sla_deadline = c.submitted_at + timedelta(hours=c.category.sla_hours)
                    Complaint.objects.filter(pk=c.pk).update(created_at=c.submitted_at)
                else:
                    c.submitted_at = now - timedelta(hours=random.randint(2, max(3, int(c.category.sla_hours * 0.8))))
                    c.sla_deadline = c.submitted_at + timedelta(hours=c.category.sla_hours)
                    Complaint.objects.filter(pk=c.pk).update(created_at=c.submitted_at)
                if c.status in (S.IN_PROGRESS, S.WAITING_INFO, S.REOPENED):
                    self._history(c, [(S.ASSIGNED, None, ""), (S.IN_PROGRESS, c.assigned_officer, "Work started")] +
                                  ([(S.WAITING_INFO, c.assigned_officer, "Please share a clearer photo")] if c.status == S.WAITING_INFO else []), end)
            # upvotes, comments, priority
            for u in random.sample(citizens, random.randint(0, 14)):
                Upvote.objects.get_or_create(complaint=c, user=u)
            c.upvotes_count = c.upvotes.count()
            if c.status == S.REOPENED:
                c.resolved_at = c.submitted_at + timedelta(hours=10)
                self._history(c, [(S.RESOLVED, c.assigned_officer, "Marked resolved"), (S.REOPENED, c.created_by, "Still not fixed")], end + timedelta(hours=1))
            p = calculate_priority(severity=c.severity, safety_risk=c.safety_risk, affected_people=c.affected_people, upvotes=c.upvotes_count,
                                   duplicates=0, days_unresolved=c.age_days, category_slug=c.category.slug, location_text=f"{c.title} {c.landmark}")
            c.priority_score, c.priority_level, c.priority_reasons = p["score"], p["level"], p["reasons"]
            c.save()
            Complaint.objects.filter(pk=c.pk).update(created_at=c.submitted_at)
            if random.random() < 0.5:
                Comment.objects.create(complaint=c, author=random.choice(citizens), text=random.choice(
                    ["Still a problem this morning.", "Thanks for looking into this.", "This is affecting many of us on the lane."]))
            if c.assigned_officer and random.random() < 0.4:
                Comment.objects.create(complaint=c, author=c.assigned_officer, text="Internal: crew availability checked with supervisor.", is_internal=True)
            Notification.objects.create(recipient=c.created_by, complaint=c, notification_type="status_changed",
                                        title=f"{c.complaint_number}: {c.get_status_display()}", message=f"Your complaint {c.complaint_number} is now {c.get_status_display().lower()}.",
                                        is_read=random.random() < 0.5)
        for parent in parents:
            parent.priority_reasons = parent.priority_reasons + ["1 duplicate report merged (+2)"]
            parent.priority_score = min(100, parent.priority_score + 2)
            parent.priority_level = priority_level_for(parent.priority_score)
            parent.save()
