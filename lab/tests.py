from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings 
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core.models import ActivityLog, User, STAFF_ROLES

from .importer import ParseError, import_results, parse_line
from .models import BMPResult, CBCResult, LipidResult, Patient, TestOrder, TestType
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
        for typed in ["call me", "520-555-014", "520-555-0142 x12", "+1 520 555 014", "25205550142", "+0123456789", "+5203732222", "５２０５５５０１４２"]:
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

    def test_list_search_finds_a_phone_however_it_is_typed(self):
        self.login_as(User.Role.CASHIER)
        make_patient(first_name="Jane", phone="520-555-0142").save()
        make_patient(first_name="Carlos", phone="520-555-0199").save()
        for query in ["5205550142", "(520) 555 0142", "5550142"]:
            with self.subTest(query=query):
                response = self.client.get(reverse("patient_list"), {"q": query})
                self.assertEqual([p.first_name for p in response.context["patients"]], ["Jane"])

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

    def test_valid_order_is_logged_once_for_its_patient(self):
        patient = self.add_patient()
        self.client.post(reverse("order_create"), self.form_data(patient))
        order = TestOrder.objects.get()
        entry = ActivityLog.objects.get(action="order_created")
        self.assertEqual(ActivityLog.objects.count(), 1)
        self.assertEqual((entry.user, entry.patient), (self.staff, patient))
        self.assertIn(f"Order #{order.pk}", entry.details)
        self.assertIn("BMP", entry.details)
        self.assertIn("Phone-in", entry.details)

    def test_invalid_order_is_not_logged(self):
        patient = self.add_patient()
        self.client.post(reverse("order_create"), {**self.form_data(patient), "tests": []})
        self.assertFalse(ActivityLog.objects.exists())

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

class OrderRoleAccessTests(TestCase):
    #setup
    def setUp(self):
        self.patient = make_patient()
        self.patient.save()
        self.order = make_order(patient=self.patient)
        self.urls = [
            reverse("order_create"),
            reverse("order_list"),
            reverse("order_detail", args=[self.order.pk]),
        ]

    def login_as(self, role):
        user = User.objects.create_user(username=f"{role}-user", role=role, must_change_password=False)
        self.client.force_login(user)
        return user

    def order_form_data(self):
        return {
            "patient": self.patient.pk,
            "source": "walk_in",
            "tests": [TestType.objects.get(code="CBC").pk],
            "physician_name": "Dr. Jorge Smith",
            "physician_license_id": "AZ-12345",
            "insurance_provider": "West Health",
            "insurance_policy_number": "POL-12345",
        }
    #tests
    def test_each_staff_role_can_create_an_order(self):
        for role in sorted(STAFF_ROLES):
            with self.subTest(role=role):
                user = self.login_as(role)
                self.assertEqual(self.client.get(reverse("order_create")).status_code, 200)
                response = self.client.post(reverse("order_create"), self.order_form_data())
                self.assertRedirects(response, reverse("order_list"))
                self.assertTrue(TestOrder.objects.filter(entered_by=user).exists())
        self.assertEqual(TestOrder.objects.count(), 1 + len(STAFF_ROLES))

    def test_patient_and_provider_roles_get_403(self):
        for role in (User.Role.PATIENT, User.Role.HEALTHCARE_PROVIDER):
            self.login_as(role)
            for url in self.urls:
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)
            with self.subTest(role=role, url="post"):
                response = self.client.post(reverse("order_create"), self.order_form_data())
                self.assertEqual(response.status_code, 403)
        self.assertEqual(TestOrder.objects.count(), 1)

    def test_logged_out_user_is_sent_to_login(self):
        for url in self.urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])
        response = self.client.post(reverse("order_create"), self.order_form_data())
        self.assertIn(reverse("login"), response["Location"])
        self.assertEqual(TestOrder.objects.count(), 1)

def make_order(codes=("BMP",), patient=None):
    """Save an order for the given panel codes, with a new patient unless one is given."""
    if patient is None:
        patient = make_patient()
        patient.save()
    cashier, _ = User.objects.get_or_create(
        username="cashier", defaults={"role": User.Role.CASHIER}
    )
    order = TestOrder.objects.create(
        patient=patient,
        source=TestOrder.Source.WALK_IN,
        physician_name="Dr. Ana Patel",
        physician_license_id="AZ-12345",
        entered_by=cashier,
    )
    order.tests.set(TestType.objects.filter(code__in=codes))
    return order


def bmp_lines(order_id, glucose="92", sodium="140", potassium="4.1"):
    return (
        f"{order_id}|Test^GLU^Glucose|{glucose}|202610211340\n"
        f"{order_id}|Test^NA^Sodium|{sodium}|202610211340\n"
        f"{order_id}|Test^K^Potassium|{potassium}|202610211341\n"
    )


def cbc_lines(order_id):
    return (
        f"{order_id}|Test^WBC^White blood cells|7.2|202610211400\n"
        f"{order_id}|Test^HGB^Hemoglobin|14.1|202610211400\n"
        f"{order_id}|Test^PLT^Platelets|250|202610211400\n"
    )


def lipid_lines(order_id):
    return (
        f"{order_id}|Test^CHOL^Total cholesterol|185|202610211420\n"
        f"{order_id}|Test^HDL^HDL cholesterol|55|202610211420\n"
        f"{order_id}|Test^LDL^LDL cholesterol|110|202610211420\n"
        f"{order_id}|Test^TRIG^Triglycerides|130|202610211420\n"
    )


class PanelResultModelTests(TestCase):
    """SXFT-55: one result model per panel, each with its own values and normal ranges."""

    def test_each_panel_has_its_own_values(self):
        self.assertEqual([a.field for a in BMPResult.ANALYTES], ["glucose", "sodium", "potassium"])
        self.assertEqual([a.field for a in CBCResult.ANALYTES], ["wbc", "hemoglobin", "platelets"])
        self.assertEqual(
            [a.field for a in LipidResult.ANALYTES],
            ["total_cholesterol", "hdl", "ldl", "triglycerides"],
        )

    def test_flags_values_outside_the_normal_range(self):
        sodium = BMPResult.analyte_for("NA")
        self.assertEqual(sodium.flag(Decimal("130")), "L")
        self.assertEqual(sodium.flag(Decimal("140")), "")
        self.assertEqual(sodium.flag(Decimal("150")), "H")

    def test_one_sided_ranges(self):
        hdl = LipidResult.analyte_for("HDL")
        ldl = LipidResult.analyte_for("LDL")
        self.assertEqual(hdl.flag(Decimal("90")), "")
        self.assertEqual(hdl.flag(Decimal("35")), "L")
        self.assertEqual(ldl.flag(Decimal("99")), "")
        self.assertEqual(ldl.flag(Decimal("100")), "H")

    def test_rows_pair_each_value_with_its_flag(self):
        order = make_order(["BMP"])
        tech = User.objects.create_user(username="tech", role=User.Role.TECHNICIAN)
        result = BMPResult.objects.create(
            order=order, performed_by=tech, measured_at=order.created_at,
            glucose=Decimal("150"), sodium=Decimal("140"), potassium=Decimal("4.0"),
        )
        self.assertEqual([flag for _, _, flag in result.rows()], ["H", "", ""])
        self.assertEqual(result.patient, order.patient)


class ParseLineTests(TestCase):
    def test_reads_a_valid_line(self):
        line = parse_line("12|Test^GLU^Glucose|92.5|202610211340", 1)
        self.assertEqual((line.barcode, line.test_id, line.value), ("12", "GLU", Decimal("92.5")))
        self.assertEqual(line.measured_at.strftime("%Y-%m-%d %H:%M"), "2026-10-21 13:40")

    def test_rejects_malformed_lines(self):
        bad = [
            "12|Test^GLU^Glucose|92",  # missing field
            "12|GLU|92|202610211340",  # no Test^ID^description
            "12|Test^GLU^Glucose|high|202610211340",  # not a number
            "12|Test^GLU^Glucose|92|2026-10-21",  # bad date
        ]
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ParseError):
                parse_line(text, 1)


class ImportResultsTests(TestCase):
    """SXFT-57: each result is matched to its order and patient; anything unmatched is rejected."""

    def setUp(self):
        self.tech = User.objects.create_user(username="tech", role=User.Role.TECHNICIAN)

    def test_saves_all_three_panels_to_their_order_and_patient(self):
        order = make_order(["BMP", "CBC", "LIPID"])
        report = import_results(bmp_lines(order.pk) + cbc_lines(order.pk) + lipid_lines(order.pk), self.tech)
        self.assertEqual(report.rejected, [])
        self.assertEqual(len(report.saved), 3)
        bmp = BMPResult.objects.get(order=order)
        self.assertEqual(bmp.potassium, Decimal("4.1"))
        self.assertEqual(bmp.performed_by, self.tech)
        self.assertEqual(bmp.measured_at.strftime("%H:%M"), "13:41")  # latest line on the panel
        self.assertEqual(CBCResult.objects.get(order=order).patient, order.patient)
        self.assertEqual(LipidResult.objects.get(order=order).ldl, Decimal("110"))

    def test_rejects_unknown_order(self):
        report = import_results(bmp_lines(9999), self.tech)
        self.assertEqual(report.rejected, [("Order 9999, BMP", "no order with this ID")])
        self.assertFalse(BMPResult.objects.exists())

    def test_rejects_panel_the_order_did_not_request(self):
        order = make_order(["BMP"])
        report = import_results(cbc_lines(order.pk), self.tech)
        self.assertEqual(report.rejected, [(f"Order {order.pk}, CBC", "the order did not request a CBC")])

    def test_rejects_removed_patient(self):
        order = make_order(["BMP"])
        order.patient.deactivate()
        report = import_results(bmp_lines(order.pk), self.tech)
        self.assertIn("removed", report.rejected[0][1])
        self.assertFalse(BMPResult.objects.exists())

    def test_rejects_incomplete_panel(self):
        order = make_order(["BMP"])
        text = "\n".join(bmp_lines(order.pk).splitlines()[:2])
        report = import_results(text, self.tech)
        self.assertEqual(report.rejected, [(f"Order {order.pk}, BMP", "missing K")])

    def test_rejects_second_result_for_the_same_panel(self):
        order = make_order(["BMP"])
        import_results(bmp_lines(order.pk), self.tech)
        report = import_results(bmp_lines(order.pk, glucose="200"), self.tech)
        self.assertIn("already has a result", report.rejected[0][1])
        self.assertEqual(BMPResult.objects.get(order=order).glucose, Decimal("92"))

    def test_rejects_unknown_test_id_and_bad_lines_but_keeps_the_rest(self):
        order = make_order(["BMP"])
        text = bmp_lines(order.pk) + f"{order.pk}|Test^XYZ^Mystery|1|202610211340\nnot a result line\n"
        report = import_results(text, self.tech)
        self.assertEqual(len(report.saved), 1)
        self.assertEqual(
            report.rejected,
            [("Line 4", "unknown Test ID 'XYZ'"), ("Line 5", "expected 4 fields separated by |")],
        )


class ResultUploadViewTests(TestCase):
    """SXFT-58: technicians upload a result file and see what was saved and rejected."""

    def login_as(self, role):
        user = User.objects.create_user(username=role, role=role, must_change_password=False)
        self.client.force_login(user)
        return user

    def upload(self, text, name="results.txt"):
        return self.client.post(
            reverse("result_upload"), {"file": SimpleUploadedFile(name, text.encode())}
        )

    def test_technician_uploads_file_and_sees_saved_and_rejected(self):
        tech = self.login_as(User.Role.TECHNICIAN)
        order = make_order(["BMP"])
        response = self.upload(bmp_lines(order.pk, glucose="150") + bmp_lines(9999))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(BMPResult.objects.get(order=order).performed_by, tech)
        self.assertContains(response, "Saved (1)")
        self.assertContains(response, "High")
        self.assertContains(response, "Order 9999, BMP")

    def test_upload_logs_summary_each_saved_panel_and_each_rejection(self):
        tech = self.login_as(User.Role.TECHNICIAN)
        bmp_order, cbc_order = make_order(["BMP"]), make_order(["CBC"])
        # Two complete panels (one per order) and one line that can't be read.
        self.upload(bmp_lines(bmp_order.pk) + cbc_lines(cbc_order.pk) + "not a result line\n", name="day1.txt")

        self.assertEqual(ActivityLog.objects.filter(user=tech).count(), 4)
        summary = ActivityLog.objects.get(action="results_imported")
        self.assertIsNone(summary.patient)
        self.assertEqual(summary.details, "day1.txt: 2 saved, 1 rejected")

        saved = ActivityLog.objects.filter(action="result_saved")
        self.assertEqual({entry.patient for entry in saved}, {bmp_order.patient, cbc_order.patient})
        self.assertEqual(
            saved.get(patient=bmp_order.patient).details,
            f"Order #{bmp_order.pk}, BMP: GLU 92 mg/dL, NA 140 mmol/L, K 4.1 mmol/L",
        )

        rejected = ActivityLog.objects.get(action="result_rejected")
        self.assertIsNone(rejected.patient)
        self.assertEqual(rejected.details, "day1.txt, Line 7: expected 4 fields separated by |")

    def test_rejects_non_txt_file(self):
        self.login_as(User.Role.TECHNICIAN)
        response = self.upload("anything", name="results.csv")
        self.assertContains(response, "Upload a .txt file.")

    def test_other_roles_are_forbidden(self):
        self.login_as(User.Role.CASHIER)
        self.assertEqual(self.client.get(reverse("result_upload")).status_code, 403)

    def test_navbar_shows_upload_link_only_to_technicians(self):
        self.login_as(User.Role.TECHNICIAN)
        self.assertContains(self.client.get(reverse("patient_list")), "Upload results")
        self.client.logout()
        self.login_as(User.Role.CASHIER)
        self.assertNotContains(self.client.get(reverse("patient_list")), "Upload results")
class ParseLineEdgeCaseTests(SimpleTestCase):
    """C6: the parser reads tidy-but-sloppy lines and rejects anything a machine shouldn't send."""

    def test_extra_spaces_and_lowercase_test_id_are_accepted(self):
        line = parse_line(" 12 | Test^glu^Glucose | 92 | 202610211340 ", 1)
        self.assertEqual((line.barcode, line.test_id, line.value), ("12", "GLU", Decimal("92")))

    def test_rejects_each_kind_of_bad_line_with_a_clear_reason(self):
        bad = {
            "|Test^GLU^Glucose|92|202610211340": "order ID is missing",
            "12|Test^GLU^Glucose|92|202610211340|extra": "expected 4 fields",
            "12|Test^GLU|92|202610211340": "Test^<Test ID>^<description>",
            "12|Result^GLU^Glucose|92|202610211340": "Test^<Test ID>^<description>",
            "12|Test^GLU^Glucose|NaN|202610211340": "is not a number",
            "12|Test^GLU^Glucose|Infinity|202610211340": "is not a number",
            "12|Test^GLU^Glucose|-4|202610211340": "is negative",
            "12|Test^GLU^Glucose|92|202613011340": "is not YYYYMMDDHHMM",  # month 13
        }
        for text, reason in bad.items():
            with self.subTest(text=text):
                with self.assertRaises(ParseError) as caught:
                    parse_line(text, 1)
                self.assertIn(reason, str(caught.exception))


class ImportEdgeCaseTests(TestCase):
    """C6: whole-file cases: empty files, blank lines, duplicates, and results landing on the right order."""

    def setUp(self):
        self.tech = User.objects.create_user(username="tech", role=User.Role.TECHNICIAN)

    def test_empty_file_saves_and_rejects_nothing(self):
        report = import_results("", self.tech)
        self.assertEqual((report.saved, report.rejected), ([], []))

    def test_blank_lines_are_skipped_but_line_numbers_stay_right(self):
        order = make_order(["BMP"])
        report = import_results("\n" + bmp_lines(order.pk) + "\nnot a result line", self.tech)
        self.assertEqual(len(report.saved), 1)
        self.assertEqual(report.rejected, [("Line 6", "expected 4 fields separated by |")])

    def test_rejects_a_value_sent_twice_on_one_panel(self):
        order = make_order(["BMP"])
        text = bmp_lines(order.pk) + f"{order.pk}|Test^GLU^Glucose|95|202610211342\n"
        report = import_results(text, self.tech)
        self.assertEqual(report.rejected, [(f"Order {order.pk}, BMP", "GLU appears more than once")])
        self.assertFalse(BMPResult.objects.exists())

    def test_rejects_order_id_that_is_not_a_number(self):
        report = import_results(bmp_lines("abc"), self.tech)
        self.assertEqual(report.rejected, [("Order abc, BMP", "no order with this ID")])

    def test_rejects_value_too_large_for_the_database(self):
        order = make_order(["BMP"])
        report = import_results(bmp_lines(order.pk, glucose="12345678"), self.tech)
        self.assertEqual(len(report.rejected), 1)
        self.assertIn("glucose", report.rejected[0][1])
        self.assertFalse(BMPResult.objects.exists())

    def test_a_bad_panel_does_not_block_another_panel_on_the_same_order(self):
        order = make_order(["BMP", "CBC"])
        incomplete_cbc = "\n".join(cbc_lines(order.pk).splitlines()[:2])
        report = import_results(bmp_lines(order.pk) + incomplete_cbc, self.tech)
        self.assertEqual(len(report.saved), 1)
        self.assertEqual(report.rejected, [(f"Order {order.pk}, CBC", "missing PLT")])
        self.assertTrue(BMPResult.objects.filter(order=order).exists())

    def test_each_order_gets_its_own_values_and_patient(self):
        first = make_order(["BMP"])
        second_patient = make_patient(first_name="John")
        second_patient.save()
        second = make_order(["BMP"], patient=second_patient)
        import_results(bmp_lines(first.pk, glucose="80") + bmp_lines(second.pk, glucose="130"), self.tech)
        self.assertEqual(BMPResult.objects.get(order=first).glucose, Decimal("80"))
        self.assertEqual(BMPResult.objects.get(order=second).glucose, Decimal("130"))
        self.assertEqual(BMPResult.objects.get(order=second).patient, second_patient)


SAMPLE_DIR = Path(settings.BASE_DIR) / "sample_data"


class SampleDataTests(TestCase):
    """C6: each file in sample_data/ imports the way it should through the real importer.

    The files use the order IDs that `seed` makes on a fresh database (1 to 30), where order N asks
    for BMP, BMP + CBC, or all three panels in turn. The test builds orders the same way and
    points the files at them, since test database IDs don't start at 1.
    """

    def setUp(self):
        self.tech = User.objects.create_user(username="tech", role=User.Role.TECHNICIAN)
        patient = make_patient()
        patient.save()
        panels = ["BMP", "CBC", "LIPID"]
        self.orders = {str(n): make_order(panels[: (n - 1) % 3 + 1], patient) for n in range(1, 11)}

    def load(self, name):
        """The sample file with each seed order ID swapped for the matching test order's ID."""
        lines = []
        for line in (SAMPLE_DIR / name).read_text(encoding="utf-8").splitlines():
            order_id, rest = line.split("|", 1)
            order = self.orders.get(order_id)
            lines.append(f"{order.pk if order else order_id}|{rest}")
        return "\n".join(lines)

    def test_valid_file_for_each_panel_saves_every_result(self):
        expected = {"chemistry_bmp.txt": 6, "hematology_cbc.txt": 4, "chemistry_lipid.txt": 3}
        for name, count in expected.items():
            with self.subTest(file=name):
                report = import_results(self.load(name), self.tech)
                self.assertEqual(report.rejected, [])
                self.assertEqual(len(report.saved), count)

    def test_some_sample_values_are_flagged_high_or_low(self):
        import_results(self.load("chemistry_bmp.txt"), self.tech)
        order_2 = BMPResult.objects.get(order=self.orders["2"])
        order_6 = BMPResult.objects.get(order=self.orders["6"])
        self.assertEqual(BMPResult.analyte_for("GLU").flag(order_2.glucose), "H")
        self.assertEqual(BMPResult.analyte_for("K").flag(order_6.potassium), "L")

    def test_broken_format_file_keeps_the_good_panel_and_rejects_the_rest(self):
        report = import_results(self.load("broken_format.txt"), self.tech)
        self.assertEqual(len(report.saved), 1)
        self.assertEqual(report.saved[0].order, self.orders["7"])
        reasons = [reason for _, reason in report.rejected]
        self.assertEqual(len(reasons), 5)
        for expected in (
            "is not a number", "expected 4 fields", "is not YYYYMMDDHHMM",
            "unknown Test ID 'XYZ'", "missing PLT",
        ):
            self.assertTrue(any(expected in reason for reason in reasons), expected)

    def test_missing_order_file_saves_nothing(self):
        report = import_results(self.load("missing_order.txt"), self.tech)
        self.assertEqual(report.saved, [])
        self.assertEqual(report.rejected, [("Order 999, BMP", "no order with this ID")])

class PatientDetailViewTests(TestCase):
    """SXFT-21 D3: a patient's details with their full order and result history."""

    def setUp(self):
        self.patient = make_patient(first_name="James", last_name="Anderson")
        self.patient.save()

    def login_as(self, role):
        user = User.objects.create_user(username=role, role=role, must_change_password=False)
        self.client.force_login(user)
        return user

    def get_page(self, pk=None):
        return self.client.get(reverse("patient_detail", args=[pk or self.patient.pk]))

    def add_bmp_result(self, order, glucose="150"):
        return BMPResult.objects.create(
            order=order, performed_by=order.entered_by, measured_at=timezone.now(),
            glucose=Decimal(glucose), sodium=Decimal("140"), potassium=Decimal("4.1"),
        )

    def test_staff_sees_the_patient(self):
        self.login_as(User.Role.CASHIER)
        response = self.get_page()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Anderson, James")

    def test_logged_out_user_is_sent_to_login(self):
        response = self.get_page()
        self.assertRedirects(response, f"{reverse('login')}?next=/patients/{self.patient.pk}/",
                             fetch_redirect_response=False)

    def test_patient_role_is_forbidden(self):
        self.login_as(User.Role.PATIENT)
        self.assertEqual(self.get_page().status_code, 403)

    def test_order_and_its_results_are_shown(self):
        self.login_as(User.Role.TECHNICIAN)
        with_result = make_order(["BMP"], patient=self.patient)
        self.add_bmp_result(with_result)
        without_result = make_order(["CBC"], patient=self.patient)

        response = self.get_page()
        self.assertContains(response, f"Order #{with_result.pk}")
        self.assertContains(response, "Glucose")
        self.assertContains(response, "150.00")
        self.assertContains(response, "70–99")
        self.assertContains(response, "High")
        self.assertContains(response, f"Order #{without_result.pk}")
        self.assertContains(response, "No results yet", count=1)
        # Newest order first.
        self.assertEqual([o.pk for o in response.context["orders"]], [without_result.pk, with_result.pk])

    def test_patient_without_orders_shows_empty_message(self):
        self.login_as(User.Role.TECHNICIAN)
        self.assertContains(self.get_page(), "No orders yet")

    def test_unknown_patient_is_404(self):
        self.login_as(User.Role.TECHNICIAN)
        self.assertEqual(self.get_page(pk=9999).status_code, 404)

    def test_removed_patient_still_shows_with_inactive_badge(self):
        self.login_as(User.Role.TECHNICIAN)
        self.patient.deactivate()
        self.assertContains(self.get_page(), "Inactive")

    def test_query_count_does_not_grow_with_orders(self):
        self.login_as(User.Role.TECHNICIAN)
        self.add_bmp_result(make_order(["BMP"], patient=self.patient))
        with CaptureQueriesContext(connection) as one_order:
            self.get_page()
        for _ in range(3):
            self.add_bmp_result(make_order(["BMP", "CBC"], patient=self.patient))
        with CaptureQueriesContext(connection) as four_orders:
            self.get_page()
        self.assertEqual(len(one_order), len(four_orders))

    def test_activity_log_shows_this_patients_entries_newest_first(self):
        tech = self.login_as(User.Role.TECHNICIAN)
        tech.first_name, tech.last_name = "Aisha", "Patel"
        tech.save()
        older = ActivityLog.objects.create(user=tech, patient=self.patient, action="order_created", details="Order #1")
        ActivityLog.objects.filter(pk=older.pk).update(timestamp=timezone.now() - timedelta(hours=1))
        ActivityLog.objects.create(user=tech, patient=self.patient, action="result_saved", details="Order #1, BMP")

        response = self.get_page()
        self.assertEqual([e.action for e in response.context["activity"]], ["result_saved", "order_created"])
        self.assertContains(response, "Aisha Patel")
        self.assertContains(response, "Order created")
        self.assertContains(response, "Result saved")
        self.assertNotContains(response, "No activity yet")

    def test_activity_log_hides_other_patients_entries(self):
        self.login_as(User.Role.TECHNICIAN)
        other = make_patient(first_name="Maria", last_name="Lopez")
        other.save()
        ActivityLog.objects.create(patient=other, action="order_created", details="someone else's order")
        response = self.get_page()
        self.assertNotContains(response, "someone else&#x27;s order")
        self.assertContains(response, "No activity yet")

    def test_activity_entry_without_user_shows_system(self):
        self.login_as(User.Role.TECHNICIAN)
        ActivityLog.objects.create(patient=self.patient, action="order_created")
        self.assertContains(self.get_page(), "<td>System</td>", html=True)

    def test_patient_without_activity_shows_empty_message(self):
        self.login_as(User.Role.TECHNICIAN)
        self.assertContains(self.get_page(), "No activity yet")

    def test_activity_log_shows_only_the_50_most_recent(self):
        self.login_as(User.Role.TECHNICIAN)
        ActivityLog.objects.bulk_create(
            ActivityLog(patient=self.patient, action="order_created", details=f"entry {n}") for n in range(55)
        )
        entries = list(self.get_page().context["activity"])
        self.assertEqual(len(entries), 50)
        self.assertEqual(entries[0].details, "entry 54")

    def test_patient_list_links_to_detail(self):
        self.login_as(User.Role.TECHNICIAN)
        response = self.client.get(reverse("patient_list"))
        self.assertContains(response, f'href="{reverse("patient_detail", args=[self.patient.pk])}"')
