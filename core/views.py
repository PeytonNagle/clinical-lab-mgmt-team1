from axes.models import AccessAttempt
from axes.utils import reset
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import LogoutView, PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.contrib.auth.decorators import login_required
from django.db.models import Max, Sum
from django.views.decorators.http import require_POST

from .decorators import role_required
from .forms import FirstPasswordForm, LabInfoForm, RegistrationForm
from .models import STAFF_ROLES, LabInfo, User
from .utils import log_event
import secrets

def home(request):
    """Send each user to their role's home page."""
    role = request.user.role
    if role not in STAFF_ROLES:
        # Patient and provider login comes with SXFT-29.
        raise PermissionDenied("This account type can't log in yet.")
    # Placeholder home pages. When a story builds a role's real home page, redirect to it here instead.
    return redirect("role_home", role=role)


def role_home(request, role):
    if role not in STAFF_ROLES:
        raise Http404
    return render(request, "core/role_home.html", {"role_label": User.Role(role).label})


class StaffLogoutView(LogoutView):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.info(request, "You've been logged out.")
        return response


class ChangePasswordView(SuccessMessageMixin, PasswordChangeView):
    template_name = "registration/password_form.html"
    success_url = reverse_lazy("home")
    success_message = "Password updated."
    extra_context = {"title": "Change password"}


class SetFirstPasswordView(ChangePasswordView):
    form_class = FirstPasswordForm
    success_message = "Password set."
    extra_context = {"title": "Set your password", "intro": "Replace your temporary password before continuing."}



@login_required
def register_staff(request):
    if request.user.role != User.Role.LAB_MANAGER:
        raise PermissionDenied("Only lab managers can create staff accounts.")

    if request.method == "POST":
        form = RegistrationForm(request.POST)

        if form.is_valid():
            user = form.save(commit=False)

            # Generate a temporary password
            temporary_password = secrets.token_urlsafe(12)
            user.set_password(temporary_password)
            user.must_change_password = True
            user.save()

            # Display the temporary password once
            return render(request, "core/staff_created.html", {
                "new_user": user,
                "temporary_password": temporary_password,
            })
    else:
        form = RegistrationForm()

    return render(request, "core/register_staff.html", {"form": form})



@role_required(User.Role.LAB_MANAGER)
def lab_info(request):
    """SXFT-16: the lab manager saves the lab's name, address and hours"""
    form = LabInfoForm(request.POST or None, instance=LabInfo.load())
    if request.method == "POST" and form.is_valid():
        info = form.save()
        log_event(request.user, "lab_info_updated", details=info.name)
        messages.success(request, "Lab info saved.")
        return redirect("lab_info")
    return render(request, "core/lab_info_form.html", {"form": form})


def locked_users():
    """Real usernames locked after too many failed logins, most recent attempt first."""
    # Axes keeps one row per username, browser and IP, and locks on their total.
    return (
        AccessAttempt.objects.filter(username__in=User.objects.values("username"))
        .values("username")
        .annotate(failures=Sum("failures_since_start"), last_attempt=Max("attempt_time"))
        .filter(failures__gte=settings.AXES_FAILURE_LIMIT)
        .order_by("-last_attempt")
    )


@role_required(User.Role.LAB_MANAGER)
def locked_accounts(request):
    """SXFT-15: the lab manager sees locked accounts and unlocks them."""
    return render(request, "core/locked_accounts.html", {"locked": locked_users()})


@role_required(User.Role.LAB_MANAGER)
@require_POST
def unlock_account(request):
    username = request.POST.get("username", "")
    # Checked first: reset() with a blank username would clear every lock.
    if not locked_users().filter(username=username).exists():
        messages.warning(request, f"{username or 'That account'} is not locked.")
        return redirect("locked_accounts")
    reset(username=username)
    log_event(request.user, "account_unlocked", details=f"{username} unlocked")
    messages.success(request, f"{username} is unlocked and can sign in again.")
    return redirect("locked_accounts")
