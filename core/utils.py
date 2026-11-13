# Shared helpers: log_event() for the activity log, notify_lab_managers() for email
import logging
import smtplib

from django.core.mail import send_mail

from .models import ActivityLog, User

logger = logging.getLogger(__name__)


def log_event(user, action, patient=None, details=""):
    """Record one entry in the activity log and return it.

    A user who is not logged in (AnonymousUser) or None is saved as no user.

    Example, in a view:
        log_event(request.user, "order_created", patient=order.patient,
                  details=f"Order {order.pk} created")
    """
    if not getattr(user, "is_authenticated", False):
        user = None
    return ActivityLog.objects.create(user=user, action=action, patient=patient, details=details)


def notify_lab_managers(subject, body):
    """Email every active lab manager who has an address. Return how many were emailed.

    A mail failure never raises: it goes to the activity log, so the caller
    (e.g. the login lockout) keeps working when the mail server is down.
    """
    recipients = list(
        User.objects.filter(role=User.Role.LAB_MANAGER, is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    if not recipients:
        return 0
    try:
        # from_email=None uses DEFAULT_FROM_EMAIL
        send_mail(subject, body, None, recipients)
    except (smtplib.SMTPException, OSError) as exc:
        logger.exception("Could not email lab managers: %s", subject)
        log_event(None, "email_failed", details=f"Email '{subject}' failed: {exc}")
        return 0
    return len(recipients)
