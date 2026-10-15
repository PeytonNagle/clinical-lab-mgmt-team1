from django.contrib import messages
from django.contrib.auth.views import LogoutView, PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from .forms import FirstPasswordForm
from .models import STAFF_ROLES, User


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
