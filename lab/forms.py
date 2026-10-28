from django import forms

from .models import Patient, TestOrder, TestType


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


def patient_label(patient):
    """Name plus birth date, so two patients with the same name can be told apart."""
    return f"{patient} · born {patient.date_of_birth:%Y-%m-%d}"


class TestOrderForm(forms.ModelForm):
    """Place an order. entered_by and status are set by the view, so they are not fields."""

    class Meta:
        model = TestOrder
        fields = ["patient", "source", "tests", "physician_name", "physician_license_id", "physician_phone"]
        widgets = {
            "source": forms.RadioSelect(attrs={"class": "form-check-input"}),
            "tests": forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("patient", "physician_name", "physician_license_id", "physician_phone"):
            css = "form-select" if name == "patient" else "form-control"
            self.fields[name].widget.attrs["class"] = css
        # Radio buttons have no "---------" choice; the model field has no default, so one must be picked.
        self.fields["source"].choices = TestOrder.Source.choices
        self.fields["tests"].label_from_instance = lambda test: f"{test.code}  {test.name}"

        self.fields["patient"].queryset = Patient.objects.filter(is_active=True)
        self.fields["patient"].label_from_instance = patient_label
        self.fields["patient"].empty_label = "Search for a patient"
