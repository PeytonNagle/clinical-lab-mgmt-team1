from io import StringIO

from django.core.management import call_command
from django.test import TestCase

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
