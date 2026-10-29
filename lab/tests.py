from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import User

from .importer import ParseError, import_results, parse_line
from .models import BMPResult, CBCResult, LipidResult, Patient, TestOrder, TestType


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
