import smtplib
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from axes.models import AccessAttempt
from django.contrib.auth.models import AnonymousUser
from django.core import mail
from django.core.management import CommandError, call_command
from django.template import RequestContext, Template
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from lab.models import Patient

from .models import ActivityLog, User, LabInfo
from .utils import log_event, notify_lab_managers


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


class LockoutTests(TestCase):
    def setUp(self):
        User.objects.create_user(
            username="tech1", password="s3cret-pass", role=User.Role.TECHNICIAN, must_change_password=False
        )

    def login(self, password="s3cret-pass", username="tech1"):
        return self.client.post("/accounts/login/", {"username": username, "password": password})

    def fail(self, times):
        for _ in range(times):
            self.login(password="wrong")

    def assert_logged_in(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_four_failures_still_allow_login(self):
        self.fail(4)
        self.assert_logged_in(self.login())

    def test_fifth_failure_locks_the_account(self):
        self.fail(5)
        response = self.login()
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "locked", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_success_resets_the_count(self):
        self.fail(4)
        self.assert_logged_in(self.login())
        self.client.logout()
        self.fail(4)
        self.assert_logged_in(self.login())

    def test_lock_does_not_expire(self):
        self.fail(5)
        AccessAttempt.objects.update(attempt_time=timezone.now() - timedelta(days=30))
        self.assertEqual(self.login().status_code, 429)

    def test_lock_is_per_username(self):
        User.objects.create_user(
            username="tech2", password="s3cret-pass", role=User.Role.TECHNICIAN, must_change_password=False
        )
        self.fail(5)
        self.assert_logged_in(self.login(username="tech2"))


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

#verify manager can correctly create a staff account
class StaffRegistrationTests(TestCase):

    def test_lab_manager_can_create_staff_account(self):
        manager = User.objects.create_user(
            username="manager_test",
            password="testpassword123",
            role=User.Role.LAB_MANAGER,
            must_change_password=False
        )

        self.client.force_login(manager)

        response = self.client.post("/staff/register/", {
            "username": "newtech",
            "first_name": "John",
            "last_name": "Smith",
            "email": "john@example.com",
            "role": User.Role.TECHNICIAN
        })

        self.assertEqual(response.status_code, 200)

        new_user = User.objects.get(username="newtech")

        self.assertEqual(new_user.role, User.Role.TECHNICIAN)

        self.assertTrue(new_user.must_change_password)

        self.assertTrue(new_user.has_usable_password())       
        temporary_password = response.context["temporary_password"]
        self.assertTrue(new_user.check_password(temporary_password))

    #verify no other type of user can create a staff account other than lab manager (tech)
    def test_non_manager_cannot_create_staff_account(self):
        technician = User.objects.create_user(
            username="tech_test",
            password="testpassword123",
            role=User.Role.TECHNICIAN,
            must_change_password=False
        )

        self.client.force_login(technician)

        response = self.client.post("/staff/register/", {
            "username": "newtech",
            "first_name": "John",
            "last_name": "Smith",
            "email": "john@example.com",
            "role": User.Role.TECHNICIAN
        })

        self.assertEqual(response.status_code, 403)

        self.assertFalse(
            User.objects.filter(username="newtech").exists()
        )

class ActivityLogTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tech1", role=User.Role.TECHNICIAN)
        self.patient = Patient.objects.create(
            first_name="Jane", last_name="Doe", date_of_birth="1990-01-01",
            gender=Patient.Gender.FEMALE, address="1 Main St", phone="555-0100",
            insurance_provider="Acme", insurance_policy_number="P-1",
        )

    def test_log_event_saves_user_action_patient_and_details(self):
        entry = log_event(self.user, "order_created", patient=self.patient, details="Order 1")

        self.assertEqual(ActivityLog.objects.count(), 1)
        saved = ActivityLog.objects.get()
        self.assertEqual(saved, entry)
        self.assertEqual(saved.user, self.user)
        self.assertEqual(saved.action, "order_created")
        self.assertEqual(saved.patient, self.patient)
        self.assertEqual(saved.details, "Order 1")

    def test_log_event_without_patient(self):
        entry = log_event(self.user, "results_imported")
        self.assertIsNone(entry.patient)
        self.assertEqual(entry.details, "")

    def test_anonymous_user_is_saved_as_none(self):
        entry = log_event(AnonymousUser(), "login_failed")
        self.assertIsNone(entry.user)

    def test_entries_come_back_newest_first(self):
        old = log_event(self.user, "first")
        new = log_event(self.user, "second")
        # Both rows can share a timestamp within one test, so push the first one into the past.
        ActivityLog.objects.filter(pk=old.pk).update(timestamp=timezone.now() - timedelta(minutes=5))

        self.assertEqual(list(ActivityLog.objects.all()), [new, old])


class LabInfoTests(TestCase):
    """SXFT-16: the lab manager stores the lab's name, address and hours; every page shows them."""

    def setUp(self):
        self.url = reverse("lab_info")

    def login_as(self, role):
        user = User.objects.create_user(username=role, role=role, must_change_password=False)
        self.client.force_login(user)
        return user

    def post_info(self, **overrides):
        data =        data = {"name": "Desert Clinical Lab", "address": "123 Main St, Tucson, AZ",  "phone": "520-555-0101", "hours": "Mon-Fri 7am-5pm"}
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_manager_saves_lab_info(self):
        self.login_as(User.Role.LAB_MANAGER)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertRedirects(self.post_info(), self.url)
        self.assertEqual(LabInfo.load().name, "Desert Clinical Lab")
        self.assertTrue(ActivityLog.objects.filter(action="lab_info_updated").exists())

    def test_saving_again_edits_the_same_row(self):
        self.login_as(User.Role.LAB_MANAGER)
        self.post_info()
        self.post_info(name="New Name")
        self.assertEqual(LabInfo.objects.count(), 1)
        self.assertEqual(LabInfo.load().name, "New Name")

    def test_all_fields_are_required(self):
        self.login_as(User.Role.LAB_MANAGER)
        response = self.post_info(name="", address="", phone="", hours="")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(LabInfo.objects.exists())

    def test_other_roles_are_forbidden(self):
        self.login_as(User.Role.SPECIMEN_COLLECTOR)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.post_info().status_code, 403)
        self.assertFalse(LabInfo.objects.exists())

    def test_footer_shows_lab_info(self):
        LabInfo.objects.create(name="Desert Clinical Lab", address="123 Main St", phone="520-555-0101", hours="Mon-Fri 7am-5pm")
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Desert Clinical Lab")
        self.assertContains(response, "520-555-0101")
        self.assertContains(response, "Mon-Fri 7am-5pm")

    def test_no_footer_before_lab_info_is_saved(self):
        self.assertNotContains(self.client.get(reverse("login")), "<footer")
    
    def test_bad_phone_is_rejected(self):
        self.login_as(User.Role.LAB_MANAGER)
        response = self.post_info(phone="not a phone")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(LabInfo.objects.exists())

    def test_lab_info_is_in_the_admin(self):
        from django.contrib import admin
        self.assertIn(LabInfo, admin.site._registry)


class NotifyLabManagersTests(TestCase):
    """SXFT-15: one email to every active lab manager that has an address."""

    def make_user(self, username, role=User.Role.LAB_MANAGER, **fields):
        return User.objects.create_user(username=username, role=role, **fields)

    def test_sends_one_email_to_every_active_manager_with_an_address(self):
        self.make_user("m1", email="m1@lab.test")
        self.make_user("m2", email="m2@lab.test")

        sent = notify_lab_managers("Locked out", "tech1 is locked out")

        self.assertEqual(sent, 2)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(sorted(mail.outbox[0].to), ["m1@lab.test", "m2@lab.test"])
        self.assertEqual(mail.outbox[0].subject, "Locked out")
        self.assertEqual(mail.outbox[0].body, "tech1 is locked out")

    def test_skips_inactive_blank_email_and_other_roles(self):
        self.make_user("ok", email="ok@lab.test")
        self.make_user("inactive", email="inactive@lab.test", is_active=False)
        self.make_user("blank", email="")
        self.make_user("tech", role=User.Role.TECHNICIAN, email="tech@lab.test")

        sent = notify_lab_managers("s", "b")

        self.assertEqual(sent, 1)
        self.assertEqual(mail.outbox[0].to, ["ok@lab.test"])

    def test_no_recipients_sends_nothing(self):
        self.make_user("blank", email="")

        self.assertEqual(notify_lab_managers("s", "b"), 0)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(ActivityLog.objects.exists())

    def test_send_failure_is_logged_not_raised(self):
        self.make_user("m1", email="m1@lab.test")

        for error in (smtplib.SMTPException("relay down"), OSError("connection refused")):
            with self.subTest(error=error):
                ActivityLog.objects.all().delete()
                with patch("core.utils.send_mail", side_effect=error):
                    with self.assertLogs("core.utils", level="ERROR"):
                        sent = notify_lab_managers("Locked out", "body")

                self.assertEqual(sent, 0)
                entry = ActivityLog.objects.get()
                self.assertEqual(entry.action, "email_failed")
                self.assertIsNone(entry.user)
                self.assertIn("Locked out", entry.details)
                self.assertIn(str(error), entry.details)

    def test_other_errors_are_not_swallowed(self):
        self.make_user("m1", email="m1@lab.test")

        with patch("core.utils.send_mail", side_effect=ValueError("bug")):
            with self.assertRaises(ValueError):
                notify_lab_managers("s", "b")
