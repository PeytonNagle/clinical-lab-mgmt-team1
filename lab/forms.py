from django import forms

from .models import Patient


class PatientForm(forms.ModelForm):
    """Create or edit a patient account. is_active is left out: removing a patient has its own page."""

    class Meta:
        model = Patient
        fields = [
            "first_name",
            "last_name",
            "date_of_birth",
            "gender",
            "address",
            "phone",
            "email",
            "insurance_provider",
            "insurance_policy_number",
        ]
        widgets = {
            # Browser date picker; format must be YYYY-MM-DD for it to show the saved value.
            "date_of_birth": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Bootstrap styling: dropdowns use form-select, everything else form-control.
        for field in self.fields.values():
            css = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            field.widget.attrs["class"] = css
