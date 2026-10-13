from io import StringIO

from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
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
                self.client.force_login(User.objects.create_user(username=role, role=role))
                response = self.client.get("/", follow=True)
                self.assertContains(response, f"{role.label} home")

    def test_patient_is_refused(self):
        self.client.force_login(User.objects.create_user(username="pat", role=User.Role.PATIENT))
        response = self.client.get("/")
        self.assertEqual(response.status_code, 403)
