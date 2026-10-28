# Shared helpers, e.g. log_event() for the activity log
from .models import ActivityLog


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
