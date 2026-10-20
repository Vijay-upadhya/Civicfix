from django.conf import settings
from django.core.mail import send_mail

from .models import Notification


def send_complaint_notification(recipient, complaint, notification_type, title, message):
    """Create an in-app notification (and an email when SMTP is configured)."""
    if recipient is None:
        return None
    note = Notification.objects.create(recipient=recipient, complaint=complaint,
                                       notification_type=notification_type, title=title, message=message)
    if settings.EMAIL_HOST and recipient.email:
        send_mail(title, message, settings.EMAIL_HOST_USER or None, [recipient.email], fail_silently=True)
    return note


def notify_many(recipients, complaint, notification_type, title, message):
    seen = set()
    for user in recipients:
        if user and user.pk not in seen:
            seen.add(user.pk)
            send_complaint_notification(user, complaint, notification_type, title, message)
