from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import STAFF_ROLES


class StaffLoginForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.role not in STAFF_ROLES:
            raise forms.ValidationError(
                f"{user.get_role_display()} accounts can't sign in here.", code="wrong_portal"
            )
