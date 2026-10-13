from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render

from .models import User

# Placeholder home pages. When a story builds a role's real home page, redirect to it here instead.
STAFF_HOME_ROLES = {
    User.Role.LAB_MANAGER,
    User.Role.SPECIMEN_COLLECTOR,
    User.Role.TECHNICIAN,
    User.Role.PATHOLOGIST,
    User.Role.CASHIER,
}


def home(request):
    """Send each user to their role's home page."""
    role = request.user.role
    if role not in STAFF_HOME_ROLES:
        # Patient and provider login comes with SXFT-29.
        raise PermissionDenied("This account type can't log in yet.")
    return redirect("role_home", role=role)


def role_home(request, role):
    if role not in STAFF_HOME_ROLES:
        raise Http404
    return render(request, "core/role_home.html", {"role_label": User.Role(role).label})
