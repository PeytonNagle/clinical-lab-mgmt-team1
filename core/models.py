from django.conf import settings
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


# Roles that sign in through the staff login. Patient and provider login comes with SXFT-29.
STAFF_ROLES = {
    User.Role.LAB_MANAGER,
    User.Role.SPECIMEN_COLLECTOR,
    User.Role.TECHNICIAN,
    User.Role.PATHOLOGIST,
    User.Role.CASHIER,
}


class ActivityLog(models.Model):
    """One entry in the audit trail: who did what, to which patient, and when."""

    # Who performed the action. Empty for system events; SET_NULL keeps the entry if the account is removed.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    # The patient the action concerns, if any. SET_NULL keeps the entry if the patient row is removed.
    patient = models.ForeignKey(
        "lab.Patient", null=True, blank=True, on_delete=models.SET_NULL, related_name="activity_logs"
    )

    # Short machine-friendly name of what happened, e.g. "order_created" or "results_imported".
    action = models.CharField(max_length=50)

    # Optional free-text description with extra context.
    details = models.TextField(blank=True)

    # Set once when the entry is created.
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Newest first.
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M} - {self.user or 'system'} - {self.action}"
