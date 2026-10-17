from django import forms
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm

from .models import STAFF_ROLES, User


class StaffLoginForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.role not in STAFF_ROLES:
            raise forms.ValidationError(
                f"{user.get_role_display()} accounts can't sign in here.", code="wrong_portal"
            )

# Extended from Django's SetPasswordForm to enforce first-time password change
class FirstPasswordForm(SetPasswordForm):
    """Replaces the temporary password a lab manager gave the user."""

    def clean_new_password1(self):
        password = self.cleaned_data["new_password1"]
        if self.user.check_password(password):
            raise forms.ValidationError("Choose a password different from your temporary one.")
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        user.must_change_password = False
        if commit:
            user.save()
        return user

class RegistrationForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "role"]
    def __init__(self, *args, **kwargs):
        super().__init__(*args,**kwargs)
        self.fields["role"].choices = [
            (value,label)
            for value, label in self.fields["role"].choices
            if value in STAFF_ROLES
        ]

