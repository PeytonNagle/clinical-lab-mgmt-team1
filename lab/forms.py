from django import forms
from django.utils.functional import cached_property
from django.utils.html import format_html, format_html_join

from .models import SELF_PAY, Patient, TestOrder, TestType
from .phone import PhoneField


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
    names = {SELF_PAY}
    for model in (Patient, TestOrder):
        # order_by() clears the model's default ordering, which would otherwise defeat distinct().
        names.update(model.objects.order_by().values_list("insurance_provider", flat=True).distinct())
    return sorted(names, key=str.lower)


def add_bootstrap_classes(form):
    """Dropdowns use form-select, everything else form-control. A widget that already has a class keeps it."""
    for field in form.fields.values():
        if "class" not in field.widget.attrs:
            field.widget.attrs["class"] = "form-select" if isinstance(field.widget, forms.Select) else "form-control"


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
        field_classes = {"phone": PhoneField}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)


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
        field_classes = {"physician_phone": PhoneField}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_bootstrap_classes(self)
        # Radio buttons have no "---------" choice; the model field has no default, so one must be picked.
        self.fields["source"].choices = TestOrder.Source.choices
        self.fields["tests"].label_from_instance = lambda test: f"{test.code}  {test.name}"

        patient_field = self.fields["patient"]
        patient_field.queryset = Patient.objects.filter(is_active=True)
        patient_field.label_from_instance = patient_label
        patient_field.empty_label = "Search for a patient"

        if not self.is_bound:
            # Opened from a patient row (?patient=): start with that patient's insurance. Removed or bad ids miss.
            insurance = self.patient_insurance.get(str(self.initial.get("patient")))
            if insurance:
                self.initial["insurance_provider"] = insurance["insurance_provider"]
                self.initial["insurance_policy_number"] = insurance["insurance_policy_number"]

    @cached_property
    def patient_insurance(self):
        """Active patients' insurance by id, used for the first fill and for the page script on pick."""
        rows = self.fields["patient"].queryset.values("pk", "insurance_provider", "insurance_policy_number")
        return {str(row["pk"]): row for row in rows}
