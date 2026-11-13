from axes.handlers.proxy import AxesProxyHandler
from axes.signals import user_locked_out
from django.conf import settings
from django.dispatch import receiver

from .utils import log_event, notify_lab_managers


@receiver(user_locked_out)
def report_lockout(sender, request, username, **kwargs):
    # Axes fires this on every attempt while locked; only report the one that caused the lock.
    if AxesProxyHandler.get_failures(request, request.axes_credentials) != settings.AXES_FAILURE_LIMIT:
        return
    log_event(None, "account_locked", details=f"{username} locked after {settings.AXES_FAILURE_LIMIT} failed logins")
    notify_lab_managers(
        f"CLMS account locked: {username}",
        f"The account {username} was locked after {settings.AXES_FAILURE_LIMIT} failed sign-in attempts in a row.\n"
        "A lab manager must unlock it before it can sign in again.",
    )
