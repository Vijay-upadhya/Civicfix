from django.core.management import call_command
from django.utils import timezone
from datetime import timedelta

from complaints.tests import Base
from complaints.models import Complaint
from .models import Notification


class SlaNotificationTests(Base):
    def test_check_sla_creates_warning_and_overdue_once(self):
        a, b = self.submitted(), self.submitted(title="Second streetlight problem here")
        now = timezone.now()
        Complaint.objects.filter(pk=a.pk).update(sla_deadline=now + timedelta(hours=10))
        Complaint.objects.filter(pk=b.pk).update(sla_deadline=now - timedelta(hours=5))
        call_command("check_sla", verbosity=0)
        self.assertTrue(Notification.objects.filter(notification_type="sla_warning", complaint=a).exists())
        self.assertTrue(Notification.objects.filter(notification_type="overdue", complaint=b).exists())
        n = Notification.objects.count()
        call_command("check_sla", verbosity=0)
        self.assertEqual(Notification.objects.count(), n)  # no repeats
