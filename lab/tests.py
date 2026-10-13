from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Patient


def make_patient(**overrides):
    """Build (unsaved) a Patient with valid values for every required field."""
    data = {
        "first_name": "Jane",
        "last_name": "Doe",
        "date_of_birth": date(1990, 5, 17),
        "gender": Patient.Gender.FEMALE,
        "address": "123 Main St, Tucson, AZ",
        "phone": "520-555-0100",
        "insurance_provider": "Acme Health",
        "insurance_policy_number": "POL-12345",
    }
    data.update(overrides)
    return Patient(**data)


class PatientModelTests(TestCase):
    def test_patient_saves_and_is_active_by_default(self):
        patient = make_patient()
        patient.full_clean()
        patient.save()
        self.assertTrue(Patient.objects.filter(pk=patient.pk).exists())
        self.assertTrue(patient.is_active)

    def test_missing_first_name_fails_validation(self):
        patient = make_patient(first_name="")
        with self.assertRaises(ValidationError) as ctx:
            patient.full_clean()
        self.assertIn("first_name", ctx.exception.message_dict)

    def test_deactivate_keeps_row_but_marks_inactive(self):
        patient = make_patient()
        patient.save()
        patient.deactivate()
        patient.refresh_from_db()
        self.assertFalse(patient.is_active)
        self.assertTrue(Patient.objects.filter(pk=patient.pk).exists())
