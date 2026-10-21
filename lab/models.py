from django.conf import settings
from django.db import models


class Patient(models.Model):
    """A person whose specimens are tested in the lab."""

    # Allowed gender values. Each entry is (value stored in DB, label shown to people).
    class Gender(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"
        OTHER = "other", "Other"
        UNKNOWN = "unknown", "Prefer not to say"

    # Patient's given name.
    first_name = models.CharField(max_length=100)

    # Patient's family name.
    last_name = models.CharField(max_length=100)

    # Date of birth (date only, no time).
    date_of_birth = models.DateField()

    # One of the Gender choices above.
    gender = models.CharField(max_length=10, choices=Gender.choices)

    # Home/mailing address on a single line.
    address = models.CharField(max_length=255)

    # Contact phone number, stored as text so it can keep "+", spaces, and dashes.
    phone = models.CharField(max_length=20)

    # Optional: not every patient has an email. blank=True lets forms leave it empty.
    email = models.EmailField(blank=True)

    # Name of the insurance company.
    insurance_provider = models.CharField(max_length=100)

    # Patient's policy/member number with that insurer.
    insurance_policy_number = models.CharField(max_length=50)

    # "Soft delete" flag: removing a patient sets this to False instead of deleting the row,
    # so their history (orders, results, bills) is kept.
    is_active = models.BooleanField(default=True)

    class Meta:
        # Default sort order for queries and the admin list.
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.last_name}, {self.first_name}"

    def deactivate(self):
        """Soft-delete this patient: mark inactive and save, keeping the row."""
        self.is_active = False
        self.save(update_fields=["is_active"])


class TestType(models.Model):
    """A kind of test the lab runs, such as a basic metabolic panel."""

    # Short, stable key (BMP, CBC, LIPID) that machine result files can refer to.
    code = models.CharField(max_length=20, unique=True)

    # Full name shown on forms and reports.
    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class TestOrder(models.Model):
    """A request to run one or more tests for a patient. Its id is the Report ID."""

    # How the request reached the lab. Each entry is (value stored in DB, label shown to people).
    class Source(models.TextChoices):
        WALK_IN = "walk_in", "Walk-in"
        PHONE_IN = "phone_in", "Phone-in"

    # Where the order stands. "Validated" joins this list with pathologist approval (SXFT-28).
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"

    # PROTECT: patients are soft-deleted, so this only stops a hard delete from wiping order history.
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="orders")

    # The tests requested. At least one is enforced by the order form, not the database.
    tests = models.ManyToManyField(TestType, related_name="orders")

    # One of the Source choices above.
    source = models.CharField(max_length=10, choices=Source.choices)

    # Ordering physician's name, as given at order time.
    physician_name = models.CharField(max_length=150)

    # The physician's own license or NPI number. Cleaned in save() so the same doctor always matches.
    physician_license_id = models.CharField(max_length=50)

    # Optional: the physician's contact number.
    physician_phone = models.CharField(max_length=20, blank=True)

    # Staff member who entered the order. PROTECT keeps that record when an account is removed.
    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="entered_orders"
    )

    # Set once when the order is created (the report's date and time).
    created_at = models.DateTimeField(auto_now_add=True)

    # One of the Status choices above.
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    class Meta:
        # Newest first, which is how the order list shows them.
        ordering = ["-created_at"]

    def __str__(self):
        return f"Order {self.pk} for {self.patient}"

    def save(self, *args, **kwargs):
        self.physician_license_id = self.physician_license_id.strip().upper()
        super().save(*args, **kwargs)
