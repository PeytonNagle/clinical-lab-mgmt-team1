from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from core.models import User

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


PATIENT_FORM_DATA = {
    "first_name": "Jane",
    "last_name": "Doe",
    "date_of_birth": "1990-05-17",
    "gender": Patient.Gender.FEMALE,
    "address": "123 Main St, Tucson, AZ",
    "phone": "520-555-0100",
    "email": "",
    "insurance_provider": "Acme Health",
    "insurance_policy_number": "POL-12345",
}


class PatientViewTests(TestCase):
    def login_as(self, role):
        user = User.objects.create_user(
            username=role, password="s3cret-pass", role=role, must_change_password=False
        )
        self.client.force_login(user)
        return user

    def test_cashier_creates_patient_with_insurance(self):
        self.login_as(User.Role.CASHIER)
        response = self.client.post(reverse("patient_create"), PATIENT_FORM_DATA)
        self.assertRedirects(response, reverse("patient_list"))
        patient = Patient.objects.get()
        self.assertEqual(patient.insurance_provider, "Acme Health")
        self.assertEqual(patient.insurance_policy_number, "POL-12345")
        self.assertTrue(patient.is_active)

    def test_create_with_missing_insurance_shows_error_and_saves_nothing(self):
        self.login_as(User.Role.CASHIER)
        data = {**PATIENT_FORM_DATA, "insurance_policy_number": ""}
        response = self.client.post(reverse("patient_create"), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("insurance_policy_number", response.context["form"].errors)
        self.assertFalse(Patient.objects.exists())

    def test_cashier_updates_patient(self):
        self.login_as(User.Role.CASHIER)
        patient = make_patient()
        patient.save()
        data = {**PATIENT_FORM_DATA, "phone": "520-555-9999"}
        response = self.client.post(reverse("patient_update", args=[patient.pk]), data)
        self.assertRedirects(response, reverse("patient_list"))
        patient.refresh_from_db()
        self.assertEqual(patient.phone, "520-555-9999")

    def test_cashier_removes_patient_and_row_is_kept(self):
        self.login_as(User.Role.CASHIER)
        patient = make_patient()
        patient.save()
        response = self.client.post(reverse("patient_remove", args=[patient.pk]))
        self.assertRedirects(response, reverse("patient_list"))
        patient.refresh_from_db()
        self.assertFalse(patient.is_active)

    def test_removed_patient_is_hidden_from_list_and_cannot_be_edited(self):
        self.login_as(User.Role.CASHIER)
        active = make_patient(first_name="Active")
        active.save()
        removed = make_patient(first_name="Removed", is_active=False)
        removed.save()
        response = self.client.get(reverse("patient_list"))
        self.assertEqual(list(response.context["patients"]), [active])
        response = self.client.get(reverse("patient_update", args=[removed.pk]))
        self.assertEqual(response.status_code, 404)

    def test_list_search_filters_by_name(self):
        self.login_as(User.Role.CASHIER)
        make_patient(first_name="Jane", last_name="Doe").save()
        make_patient(first_name="Carlos", last_name="Garcia").save()
        response = self.client.get(reverse("patient_list"), {"q": "garc"})
        self.assertEqual([p.last_name for p in response.context["patients"]], ["Garcia"])

    def test_technician_can_create_but_not_remove(self):
        self.login_as(User.Role.TECHNICIAN)
        response = self.client.post(reverse("patient_create"), PATIENT_FORM_DATA)
        self.assertRedirects(response, reverse("patient_list"))
        patient = Patient.objects.get()
        response = self.client.post(reverse("patient_remove", args=[patient.pk]))
        self.assertEqual(response.status_code, 403)
        patient.refresh_from_db()
        self.assertTrue(patient.is_active)

    def test_lab_manager_and_collector_can_remove(self):
        for role in (User.Role.LAB_MANAGER, User.Role.SPECIMEN_COLLECTOR):
            with self.subTest(role=role):
                self.login_as(role)
                patient = make_patient()
                patient.save()
                self.client.post(reverse("patient_remove", args=[patient.pk]))
                patient.refresh_from_db()
                self.assertFalse(patient.is_active)

    def test_get_on_remove_only_shows_confirmation(self):
        self.login_as(User.Role.CASHIER)
        patient = make_patient()
        patient.save()
        response = self.client.get(reverse("patient_remove", args=[patient.pk]))
        self.assertEqual(response.status_code, 200)
        patient.refresh_from_db()
        self.assertTrue(patient.is_active)

    def test_non_staff_role_is_forbidden(self):
        self.login_as(User.Role.PATIENT)
        response = self.client.get(reverse("patient_list"))
        self.assertEqual(response.status_code, 403)

    def test_logged_out_user_is_sent_to_login(self):
        response = self.client.get(reverse("patient_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
