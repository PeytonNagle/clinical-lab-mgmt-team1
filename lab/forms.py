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


class ResultUploadForm(forms.Form):
    """A machine result .txt file uploaded by a technician."""

    # Plenty for a day of synthetic results; stops someone uploading something huge by mistake.
    MAX_SIZE = 1024 * 1024

    file = forms.FileField(
        label="Result file (.txt)",
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".txt"}),
    )

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith(".txt"):
            raise forms.ValidationError("Upload a .txt file.")
        if upload.size > self.MAX_SIZE:
            raise forms.ValidationError("The file is larger than 1 MB.")
        try:
            return upload.read().decode("utf-8")
        except UnicodeDecodeError:
            raise forms.ValidationError("The file is not plain text.")
