from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import UserProfile
from complaints.models import OPEN_STATUSES, Complaint, Status
from notifications.services import notify_many, send_complaint_notification


class Command(BaseCommand):
    help = "Create SLA notifications (24h remaining, overdue, unassigned critical, department overdue threshold). Run hourly via cron."

    def handle(self, *args, **opts):
        now = timezone.now()
        open_qs = Complaint.objects.filter(status__in=OPEN_STATUSES, sla_deadline__isnull=False)
        n = 0
        for c in open_qs.filter(sla_deadline__gt=now, sla_deadline__lte=now + timedelta(hours=24), sla_24h_notified=False):
            notify_many([c.assigned_officer], c, "sla_warning", "SLA deadline approaching", f"{c.display_number} is due in under 24 hours.")
            c.sla_24h_notified = True
            c.save(update_fields=["sla_24h_notified"])
            n += 1
        for c in open_qs.filter(sla_deadline__lt=now, sla_overdue_notified=False):
            who = [c.assigned_officer, c.created_by]
            notify_many(who, c, "overdue", "Complaint overdue", f"{c.display_number} has passed its SLA deadline.")
            c.sla_overdue_notified = True
            c.save(update_fields=["sla_overdue_notified"])
            n += 1
        admins = [p.user for p in UserProfile.objects.filter(role="admin").select_related("user")]
        for c in open_qs.filter(priority_level="CRITICAL", assigned_officer__isnull=True):
            notify_many(admins, c, "critical_unassigned", "Critical complaint unassigned", f"{c.display_number} is critical and has no officer.")
            n += 1
        over = (open_qs.filter(sla_deadline__lt=now).values("department__name").annotate(n=Count("id"))
                .filter(n__gte=settings.OVERDUE_ALERT_THRESHOLD))
        for row in over:
            notify_many(admins, None, "department_overdue", "Department overdue threshold",
                        f"{row['department__name']} has {row['n']} overdue complaints.")
            n += 1
        self.stdout.write(self.style.SUCCESS(f"Created {n} SLA notifications."))
