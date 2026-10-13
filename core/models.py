from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user for CLMS. Inherits username, password, email, names, etc. from AbstractUser."""

    # The set of roles a user can have. Each entry is (value stored in DB, label shown to people).
    class Role(models.TextChoices):
        LAB_MANAGER = "lab_manager", "Lab Manager"
        SPECIMEN_COLLECTOR = "specimen_collector", "Specimen Collector"
        TECHNICIAN = "technician", "Lab Technician"
        PATHOLOGIST = "pathologist", "Pathologist"
        CASHIER = "cashier", "Cashier"
        PATIENT = "patient", "Patient"
        HEALTHCARE_PROVIDER = "healthcare_provider", "Healthcare Provider"

    # What this user does in the lab; controls what they will be allowed to see and do.
    role = models.CharField(max_length=30, choices=Role.choices)

    # True until the user sets their own password (e.g. after an admin creates the account).
    must_change_password = models.BooleanField(default=True)

    # Extra fields `createsuperuser` will prompt for (username and password are always asked).
    REQUIRED_FIELDS = ["email", "role"]

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
