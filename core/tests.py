from io import StringIO

from django.contrib.auth.models import AnonymousUser
from django.core.management import CommandError, call_command
from django.template import RequestContext, Template
from django.test import RequestFactory, TestCase

from lab.models import Patient

from .models import User


class UserModelTests(TestCase):
    def test_new_user_must_change_password_and_keeps_role(self):
        user = User.objects.create_user(
            username="tech1", password="s3cret-pass", role=User.Role.TECHNICIAN
        )
        self.assertTrue(user.must_change_password)
        self.assertEqual(user.role, User.Role.TECHNICIAN)

    def test_role_has_seven_choices(self):
        self.assertEqual(len(User.Role.choices), 7)


class SeedCommandTests(TestCase):
    def test_seed_twice_does_not_duplicate(self):
        call_command("seed", stdout=StringIO())
        call_command("seed", stdout=StringIO())

        seeded = ["manager1", "collector1", "tech1", "pathologist1", "cashier1"]
        self.assertEqual(User.objects.filter(username__in=seeded).count(), 5)
        self.assertEqual(User.objects.count(), 5)
        self.assertEqual(Patient.objects.count(), 10)


class BaseTemplateTests(TestCase):
    def render_page(self, user):
        request = RequestFactory().get("/")
        request.user = user
        page = Template('{% extends "base.html" %}{% block content %}page body{% endblock %}')
        return page.render(RequestContext(request))

    def test_navbar_shows_user_only_when_logged_in(self):
        user = User.objects.create_user(
            username="tech1", first_name="Aisha", last_name="Patel", role=User.Role.TECHNICIAN
        )
        logged_in = self.render_page(user)
        self.assertIn("Aisha Patel", logged_in)
        self.assertIn("Lab Technician", logged_in)

        anonymous = self.render_page(AnonymousUser())
        self.assertIn("page body", anonymous)
        self.assertNotIn("Lab Technician", anonymous)


class HomeRedirectTests(TestCase):
    def test_logged_out_user_is_sent_to_login(self):
        response = self.client.get("/")
        self.assertRedirects(response, "/accounts/login/?next=/", fetch_redirect_response=False)

    def test_each_staff_role_lands_on_its_home_page(self):
        staff_roles = [
            User.Role.LAB_MANAGER,
            User.Role.SPECIMEN_COLLECTOR,
            User.Role.TECHNICIAN,
            User.Role.PATHOLOGIST,
            User.Role.CASHIER,
        ]
        for role in staff_roles:
            with self.subTest(role=role):
                self.client.force_login(User.objects.create_user(username=role, role=role, must_change_password=False))
                response = self.client.get("/", follow=True)
                self.assertContains(response, f"{role.label} home")

    def test_patient_is_refused(self):
        self.client.force_login(User.objects.create_user(username="pat", role=User.Role.PATIENT, must_change_password=False))
        response = self.client.get("/")
        self.assertEqual(response.status_code, 403)


class StaffLoginTests(TestCase):
    def login(self, username, password="s3cret-pass"):
        return self.client.post("/accounts/login/", {"username": username, "password": password}, follow=True)

    def test_correct_password_lands_on_role_home(self):
        User.objects.create_user(
            username="tech1", password="s3cret-pass", role=User.Role.TECHNICIAN, must_change_password=False
        )
        response = self.login("tech1")
        self.assertRedirects(response, "/home/technician/", target_status_code=200)

    def test_wrong_password_is_rejected(self):
        User.objects.create_user(
            username="tech1", password="s3cret-pass", role=User.Role.TECHNICIAN, must_change_password=False
        )
        response = self.login("tech1", password="wrong")
        self.assertFalse(response.context["user"].is_authenticated)
        self.assertTrue(response.context["form"].errors)

    def test_patient_is_blocked_on_staff_login(self):
        User.objects.create_user(
            username="pat1", password="s3cret-pass", role=User.Role.PATIENT, must_change_password=False
        )
        response = self.login("pat1")
        self.assertFalse(response.context["user"].is_authenticated)
        self.assertContains(response, "Patient accounts can&#x27;t sign in here.")


class PasswordTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tech1", password="temp-pass-123", role=User.Role.TECHNICIAN)
        self.client.force_login(self.user)

    def test_flagged_user_is_forced_to_set_password(self):
        response = self.client.get("/home/technician/")
        self.assertRedirects(response, "/accounts/password/set/")

    def test_setting_password_clears_flag(self):
        reused = self.client.post(
            "/accounts/password/set/", {"new_password1": "temp-pass-123", "new_password2": "temp-pass-123"}
        )
        self.assertTrue(reused.context["form"].errors)

        response = self.client.post(
            "/accounts/password/set/", {"new_password1": "fresh-pass-456", "new_password2": "fresh-pass-456"}, follow=True
        )
        self.assertRedirects(response, "/home/technician/")
        self.user.refresh_from_db()
        self.assertFalse(self.user.must_change_password)
        self.assertTrue(self.user.check_password("fresh-pass-456"))

    def test_change_password_saves_new_password(self):
        self.user.must_change_password = False
        self.user.save()
        self.client.post(
            "/accounts/password/change/",
            {"old_password": "temp-pass-123", "new_password1": "fresh-pass-456", "new_password2": "fresh-pass-456"},
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("fresh-pass-456"))


class CreateLabManagerCommandTests(TestCase):
    def test_creates_lab_manager_with_temporary_password(self):
        out = StringIO()
        call_command("create_lab_manager", "boss", stdout=out)

        temporary_password = out.getvalue().split("Temporary password: ")[1].split()[0]
        user = User.objects.get(username="boss")
        self.assertEqual(user.role, User.Role.LAB_MANAGER)
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.check_password(temporary_password))

    def test_refuses_existing_username(self):
        User.objects.create_user(username="boss", role=User.Role.TECHNICIAN)
        with self.assertRaises(CommandError):
            call_command("create_lab_manager", "boss", stdout=StringIO())
