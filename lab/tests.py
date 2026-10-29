from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import User

from .models import Patient, TestOrder, TestType
from .phone import normalize_phone


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


class NormalizePhoneTests(SimpleTestCase):
    def test_every_accepted_format_becomes_the_recommended_one(self):
        for typed in ["5205550142", "520-555-0142", "(520) 555-0142", "520.555.0142", " 520 555 0142 ", "+1 520 555 0142", "1-520-555-0142"]:
            with self.subTest(typed=typed):
                self.assertEqual(normalize_phone(typed), "520-555-0142")

    def test_a_number_with_another_country_code_is_kept_as_plus_digits(self):
        self.assertEqual(normalize_phone("+44 20 7946 0958"), "+442079460958")

    def test_numbers_that_cannot_be_read_are_rejected(self):
        for typed in ["call me", "520-555-014", "520-555-0142 x12", "+1 520 555 014", "+12", "25205550142"]:
            with self.subTest(typed=typed):
                with self.assertRaises(ValidationError):
                    normalize_phone(typed)


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

    def test_policy_number_with_a_bad_character_is_rejected(self):
        self.login_as(User.Role.CASHIER)
        data = {**PATIENT_FORM_DATA, "insurance_policy_number": "POL 12345"}
        response = self.client.post(reverse("patient_create"), data)
        self.assertEqual(list(response.context["form"].errors), ["insurance_policy_number"])
        self.assertFalse(Patient.objects.exists())

    def test_patient_phone_is_cleaned_and_an_unreadable_one_is_rejected(self):
        self.login_as(User.Role.CASHIER)
        self.client.post(reverse("patient_create"), {**PATIENT_FORM_DATA, "phone": "(520) 555 0142"})
        self.assertEqual(Patient.objects.get().phone, "520-555-0142")
        response = self.client.post(reverse("patient_create"), {**PATIENT_FORM_DATA, "phone": "call me"})
        self.assertEqual(list(response.context["form"].errors), ["phone"])
        self.assertEqual(Patient.objects.count(), 1)

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


class TestOrderModelTests(TestCase):
    def make_order(self, **overrides):
        patient = make_patient()
        patient.save()
        cashier = User.objects.create_user(
            username="cashier", password="s3cret-pass", role=User.Role.CASHIER
        )
        data = {
            "patient": patient,
            "source": TestOrder.Source.WALK_IN,
            "physician_name": "Dr. Ana Patel",
            "physician_license_id": "AZ-12345",
            "entered_by": cashier,
        }
        data.update(overrides)
        return TestOrder.objects.create(**data)

    def test_migrate_seeds_bmp_cbc_and_lipid_panel(self):
        self.assertEqual(
            dict(TestType.objects.values_list("code", "name")),
            {
                "BMP": "Basic metabolic panel",
                "CBC": "Complete blood count",
                "LIPID": "Lipid panel",
            },
        )

    def test_order_with_several_tests_is_pending_and_listed_under_patient(self):
        order = self.make_order()
        order.tests.set(TestType.objects.all())
        order.refresh_from_db()
        self.assertEqual(order.status, TestOrder.Status.PENDING)
        self.assertEqual(order.tests.count(), 3)
        self.assertEqual(list(order.patient.orders.all()), [order])

    def test_physician_license_id_is_trimmed_and_uppercased_on_save(self):
        order = self.make_order(physician_license_id="  az-12345 ")
        order.refresh_from_db()
        self.assertEqual(order.physician_license_id, "AZ-12345")


class OrderViewTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="tech", password="s3cret-pass", role=User.Role.TECHNICIAN, must_change_password=False
        )
        self.client.force_login(self.staff)

    def add_patient(self, **overrides):
        patient = make_patient(**overrides)
        patient.save()
        return patient

    def add_order(self, patient=None, codes=("BMP",), **overrides):
        data = {
            "patient": patient or self.add_patient(),
            "source": TestOrder.Source.WALK_IN,
            "physician_name": "Dr. Ana Patel",
            "physician_license_id": "AZ-12345",
            "insurance_provider": "Acme Health",
            "insurance_policy_number": "POL-12345",
            "entered_by": self.staff,
        }
        data.update(overrides)
        order = TestOrder.objects.create(**data)
        order.tests.set(TestType.objects.filter(code__in=codes))
        return order

    def form_data(self, patient, **overrides):
        data = {
            "patient": patient.pk,
            "source": "phone_in",
            "tests": list(TestType.objects.filter(code__in=["BMP", "LIPID"]).values_list("pk", flat=True)),
            "physician_name": "Dr. Ana Patel",
            "physician_license_id": "  az-12345 ",
            "physician_phone": " (520) 555-0199 ",
            "insurance_provider": "  Aetna ",
            "insurance_policy_number": " AET-558812 ",
        }
        data.update(overrides)
        return data

    def test_staff_places_order_and_lands_on_the_list(self):
        patient = self.add_patient(first_name="James", last_name="Anderson")
        response = self.client.post(reverse("order_create"), self.form_data(patient), follow=True)
        order = TestOrder.objects.get()
        self.assertRedirects(response, reverse("order_list"))
        self.assertContains(response, f"Order #{order.pk} created for Anderson, James")
        self.assertEqual(order.patient, patient)
        self.assertEqual(order.entered_by, self.staff)
        self.assertEqual(order.status, TestOrder.Status.PENDING)
        self.assertEqual(order.source, TestOrder.Source.PHONE_IN)
        self.assertEqual(order.physician_license_id, "AZ-12345")
        self.assertEqual(order.physician_phone, "520-555-0199")
        self.assertEqual((order.insurance_provider, order.insurance_policy_number), ("Aetna", "AET-558812"))
        self.assertEqual(sorted(order.tests.values_list("code", flat=True)), ["BMP", "LIPID"])

    def test_each_required_field_is_enforced_and_nothing_is_saved(self):
        patient = self.add_patient()
        blanks = {
            "patient": "",
            "source": "",
            "tests": [],
            "physician_name": "   ",
            "physician_license_id": "   ",
            "insurance_provider": "   ",
            "insurance_policy_number": "   ",
        }
        for field, blank in blanks.items():
            with self.subTest(field=field):
                data = {**self.form_data(patient), field: blank}
                response = self.client.post(reverse("order_create"), data)
                self.assertEqual(list(response.context["form"].errors), [field])
        self.assertFalse(TestOrder.objects.exists())

    def test_physician_phone_is_optional_but_must_be_readable_if_given(self):
        patient = self.add_patient()
        self.client.post(reverse("order_create"), self.form_data(patient, physician_phone=""))
        self.assertEqual(TestOrder.objects.get().physician_phone, "")
        response = self.client.post(reverse("order_create"), self.form_data(patient, physician_phone="call me"))
        self.assertEqual(list(response.context["form"].errors), ["physician_phone"])
        self.assertEqual(TestOrder.objects.count(), 1)

    def test_order_keeps_its_own_insurance_when_the_patient_changes_later(self):
        patient = self.add_patient()
        data = self.form_data(patient, insurance_provider="Cigna", insurance_policy_number="CIG-330945")
        self.client.post(reverse("order_create"), data)
        patient.insurance_provider = "Humana"
        patient.save()
        order = TestOrder.objects.get()
        self.assertEqual((order.insurance_provider, order.insurance_policy_number), ("Cigna", "CIG-330945"))

    def test_policy_number_with_a_space_is_rejected_on_its_own_field(self):
        response = self.client.post(reverse("order_create"), self.form_data(self.add_patient(), insurance_policy_number="AET 558812"))
        self.assertEqual(list(response.context["form"].errors), ["insurance_policy_number"])
        self.assertFalse(TestOrder.objects.exists())

    def test_self_pay_is_accepted_in_both_insurance_fields(self):
        data = self.form_data(self.add_patient(), insurance_provider="SELF-PAY", insurance_policy_number="SELF-PAY")
        self.client.post(reverse("order_create"), data)
        order = TestOrder.objects.get()
        self.assertEqual((order.insurance_provider, order.insurance_policy_number), ("SELF-PAY", "SELF-PAY"))

    def test_patient_in_url_fills_in_their_insurance_only_if_active(self):
        active = self.add_patient(insurance_provider="Aetna", insurance_policy_number="AET-558812")
        removed = self.add_patient(insurance_provider="Humana", insurance_policy_number="HUM-610284")
        removed.deactivate()
        response = self.client.get(reverse("order_create"), {"patient": active.pk})
        self.assertContains(response, 'value="Aetna"')
        self.assertContains(response, 'value="AET-558812"')
        response = self.client.get(reverse("order_create"), {"patient": removed.pk})
        self.assertNotContains(response, 'value="HUM-610284"')

    def test_patient_dropdown_is_labelled_and_a_bad_patient_in_url_is_ignored(self):
        self.add_patient()
        for query in ({}, {"patient": "abc"}, {"patient": "²"}, {"patient": "99999999999999999999999"}):
            with self.subTest(query=query):
                response = self.client.get(reverse("order_create"), query)
                self.assertContains(response, "Search for a patient")
                self.assertContains(response, "born 1990-05-17")

    def test_both_forms_suggest_stored_providers_and_self_pay(self):
        self.add_patient(insurance_provider="Aetna")
        self.add_order(insurance_provider="Cigna")
        for name in ("order_create", "patient_create"):
            response = self.client.get(reverse(name))
            for provider in ("Aetna", "Cigna", "SELF-PAY"):
                with self.subTest(form=name, provider=provider):
                    self.assertContains(response, f'<option value="{provider}">')

    def test_removed_patient_cannot_be_ordered_for(self):
        patient = self.add_patient()
        patient.deactivate()
        response = self.client.post(reverse("order_create"), self.form_data(patient))
        self.assertIn("patient", response.context["form"].errors)
        self.assertFalse(TestOrder.objects.exists())

    def test_patient_in_url_is_preselected_only_if_active(self):
        active = self.add_patient(first_name="James", last_name="Anderson")
        removed = self.add_patient(first_name="Gone", last_name="Smith")
        removed.deactivate()
        self.assertContains(
            self.client.get(reverse("order_create"), {"patient": active.pk}), f'<option value="{active.pk}" selected>'
        )
        response = self.client.get(reverse("order_create"), {"patient": removed.pk})
        self.assertNotContains(response, "selected>")
        self.assertNotContains(response, "Smith, Gone")

    def test_patient_and_provider_roles_are_forbidden(self):
        order = self.add_order()
        urls = [
            reverse("order_create"),
            reverse("order_list"),
            reverse("order_detail", args=[order.pk]),
        ]
        for role in (User.Role.PATIENT, User.Role.HEALTHCARE_PROVIDER):
            self.client.force_login(
                User.objects.create_user(username=role, password="s3cret-pass", role=role, must_change_password=False)
            )
            for url in urls:
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
            with self.subTest(role=role, url="post"):
                response = self.client.post(reverse("order_create"), self.form_data(order.patient))
                self.assertEqual(response.status_code, 403)
        self.assertEqual(TestOrder.objects.count(), 1)

    def test_list_shows_newest_first_and_keeps_orders_of_removed_patients(self):
        older = self.add_order(self.add_patient(first_name="James", last_name="Anderson"), codes=("BMP", "CBC"))
        TestOrder.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=1))
        removed = self.add_patient(first_name="Rosa", last_name="Lopez")
        self.add_order(removed, source=TestOrder.Source.PHONE_IN)
        removed.deactivate()

        html = self.client.get(reverse("order_list")).content.decode()
        self.assertLess(html.index("Lopez, Rosa"), html.index("Anderson, James"))
        for text in ("BMP, CBC", "Phone-in", "Walk-in", "Pending", "Removed"):
            self.assertIn(text, html)

    def test_list_is_paginated_25_per_page(self):
        oldest = self.add_order()
        for _ in range(25):
            self.add_order()
        oldest_url = reverse("order_detail", args=[oldest.pk])
        self.assertNotContains(self.client.get(reverse("order_list")), oldest_url)
        self.assertContains(self.client.get(reverse("order_list"), {"page": 2}), oldest_url)

    def test_detail_shows_whole_order_even_if_patient_was_removed(self):
        order = self.add_order(
            codes=("BMP", "LIPID"),
            physician_phone="520-555-0199",
            insurance_provider="Cigna",
            insurance_policy_number="CIG-330945",
        )
        order.patient.deactivate()
        response = self.client.get(reverse("order_detail", args=[order.pk]))
        for text in (
            "Dr. Ana Patel", "AZ-12345", "520-555-0199", "Cigna", "CIG-330945", "tech", "Doe, Jane",
            "Basic metabolic panel", "Lipid panel",
        ):
            self.assertContains(response, text)
