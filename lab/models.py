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
