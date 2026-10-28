from django import forms
from django.core.exceptions import ValidationError
from django.utils.html import format_html, format_html_join

from .models import SELF_PAY, Patient, TestOrder, TestType


class DatalistInput(forms.TextInput):
    """A text box that suggests values as you type but still accepts anything. `options` is called on each render."""

    def __init__(self, options, attrs=None):
        super().__init__(attrs)
        self.options = options

    def render(self, name, value, attrs=None, renderer=None):
        list_id = f"{name}-options"
        box = super().render(name, value, {**(attrs or {}), "list": list_id}, renderer)
        items = format_html_join("", '<option value="{}">', ((option,) for option in self.options()))
        return box + format_html('<datalist id="{}">{}</datalist>', list_id, items)


def provider_names():
    """Insurers already on file, so one insurer isn't typed several ways, plus the no-insurance value."""
    names = set(Patient.objects.values_list("insurance_provider", flat=True))
    names |= set(TestOrder.objects.values_list("insurance_provider", flat=True))
    return sorted(names | {SELF_PAY}, key=str.lower)


# Used by both the patient form and the order form.
INSURANCE_WIDGETS = {
    "insurance_provider": DatalistInput(provider_names),
    "insurance_policy_number": DatalistInput(lambda: [SELF_PAY]),
}


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
            **INSURANCE_WIDGETS,
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
        fields = [
            "patient",
            "source",
            "tests",
            "physician_name",
            "physician_license_id",
            "physician_phone",
            "insurance_provider",
            "insurance_policy_number",
        ]
        widgets = {
            "source": forms.RadioSelect(attrs={"class": "form-check-input"}),
            "tests": forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
            **INSURANCE_WIDGETS,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name not in ("source", "tests"):
                field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
        # Radio buttons have no "---------" choice; the model field has no default, so one must be picked.
        self.fields["source"].choices = TestOrder.Source.choices
        self.fields["tests"].label_from_instance = lambda test: f"{test.code}  {test.name}"

        patient_field = self.fields["patient"]
        patient_field.queryset = Patient.objects.filter(is_active=True)
        patient_field.label_from_instance = patient_label
        patient_field.empty_label = "Search for a patient"

        if not self.is_bound:
            # Opened from a patient row (?patient=): start with that patient's insurance.
            try:
                patient = patient_field.clean(self.initial.get("patient"))
            except ValidationError:
                return
            self.initial["insurance_provider"] = patient.insurance_provider
            self.initial["insurance_policy_number"] = patient.insurance_policy_number
