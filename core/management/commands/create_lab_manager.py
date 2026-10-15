"""
Create the first lab manager for a new lab. Only lab managers can create accounts, so someone with
server access (IT or a developer) runs this once during setup, or to recover a lab with no managers.

Usage: python manage.py create_lab_manager <username> [--email EMAIL]
"""

import secrets

from django.core.management.base import BaseCommand, CommandError

from core.models import User


class Command(BaseCommand):
    help = "Create a lab manager account with a temporary password they must change on first login."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--email", default="")

    def handle(self, *args, username, email, **options):
        if User.objects.filter(username=username).exists():
            raise CommandError(f'A user named "{username}" already exists.')

        # Printed once and never stored in plain text; the manager replaces it on first login.
        temporary_password = secrets.token_urlsafe(9)
        User.objects.create_user(
            username=username,
            email=email,
            password=temporary_password,
            role=User.Role.LAB_MANAGER,
            must_change_password=True,
        )

        self.stdout.write(self.style.SUCCESS(f'Created lab manager "{username}".'))
        self.stdout.write(f"Temporary password: {temporary_password}")
        self.stdout.write("They will be asked to choose a new password on first login.")
