from decimal import Decimal

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

# What staff enter when a patient has no insurance. It passes the policy number rule below.
SELF_PAY = "SELF-PAY"

# Shared by the patient and the order, so a patient can't be saved with a number the order form would reject.
policy_number_validator = RegexValidator(r"\A[A-Za-z0-9-]+\Z", "Use letters, numbers and hyphens only.")


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

    # Contact phone number, saved as 520-555-0101 (or +digits abroad) by the form; see phone.py.
    phone = models.CharField(max_length=20)

    # Optional: not every patient has an email. blank=True lets forms leave it empty.
    email = models.EmailField(blank=True)

    # Name of the insurance company.
    insurance_provider = models.CharField(max_length=100)

    # Patient's policy/member number with that insurer.
    insurance_policy_number = models.CharField(max_length=50, validators=[policy_number_validator])

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

    # Insurance as it was when the order was placed, copied from the patient and correctable per order.
    # Later edits to the patient's insurance do not change past orders.
    insurance_provider = models.CharField(max_length=100)
    insurance_policy_number = models.CharField(max_length=50, validators=[policy_number_validator])

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


class Analyte:
    """One measured value on a panel: its machine Test ID, model field, units and normal range."""

    def __init__(self, test_id, field, label, units, low=None, high=None):
        self.test_id = test_id
        self.field = field
        self.label = label
        self.units = units
        # Normal range, inclusive. None means no limit on that side (e.g. HDL has no upper limit).
        self.low = None if low is None else Decimal(str(low))
        self.high = None if high is None else Decimal(str(high))

    def range_display(self):
        if self.low is None:
            return f"≤ {self.high}"
        if self.high is None:
            return f"≥ {self.low}"
        return f"{self.low}–{self.high}"

    def flag(self, value):
        """'L' below the normal range, 'H' above it, '' inside it."""
        if self.low is not None and value < self.low:
            return "L"
        if self.high is not None and value > self.high:
            return "H"
        return ""


def result_value_field():
    return models.DecimalField(max_digits=8, decimal_places=2)


class PanelResult(models.Model):
    """Shared fields for one panel's results on one order. Each panel subclass adds its own values."""

    # TestType.code this panel belongs to (BMP, CBC, LIPID). Set by each subclass.
    TEST_CODE = None

    # The values on this panel, in display order. Set by each subclass. Ranges are fixed adult ranges.
    ANALYTES = []

    # One result per panel per order. PROTECT keeps results when someone tries to hard-delete an order.
    order = models.OneToOneField(TestOrder, on_delete=models.PROTECT, related_name="%(class)s")

    # Technician who uploaded the machine file.
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="%(class)s_performed"
    )

    # When the machine produced the result (from the file).
    measured_at = models.DateTimeField()

    # When the result was saved in the system.
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["-measured_at"]

    def __str__(self):
        return f"{self.TEST_CODE} result for order {self.order_id}"

    @property
    def patient(self):
        return self.order.patient

    @classmethod
    def analyte_for(cls, test_id):
        """The Analyte with this machine Test ID, or None if it's not on this panel."""
        return next((a for a in cls.ANALYTES if a.test_id == test_id), None)

    def rows(self):
        """(analyte, value, flag) for each value, for templates and reports."""
        return [(a, getattr(self, a.field), a.flag(getattr(self, a.field))) for a in self.ANALYTES]


class BMPResult(PanelResult):
    """Basic metabolic panel from the chemistry analyzer."""

    TEST_CODE = "BMP"
    ANALYTES = [
        Analyte("GLU", "glucose", "Glucose", "mg/dL", 70, 99),
        Analyte("NA", "sodium", "Sodium", "mmol/L", 135, 145),
        Analyte("K", "potassium", "Potassium", "mmol/L", 3.5, 5.0),
    ]

    glucose = result_value_field()
    sodium = result_value_field()
    potassium = result_value_field()


class CBCResult(PanelResult):
    """Complete blood count from the hematology analyzer."""

    TEST_CODE = "CBC"
    ANALYTES = [
        Analyte("WBC", "wbc", "White blood cells", "10^3/µL", 4.5, 11.0),
        Analyte("HGB", "hemoglobin", "Hemoglobin", "g/dL", 12.0, 17.5),
        Analyte("PLT", "platelets", "Platelets", "10^3/µL", 150, 450),
    ]

    wbc = result_value_field()
    hemoglobin = result_value_field()
    platelets = result_value_field()


class LipidResult(PanelResult):
    """Lipid panel from the chemistry analyzer."""

    TEST_CODE = "LIPID"
    ANALYTES = [
        Analyte("CHOL", "total_cholesterol", "Total cholesterol", "mg/dL", high=199),
        Analyte("HDL", "hdl", "HDL cholesterol", "mg/dL", low=40),
        Analyte("LDL", "ldl", "LDL cholesterol", "mg/dL", high=99),
        Analyte("TRIG", "triglycerides", "Triglycerides", "mg/dL", high=149),
    ]

    total_cholesterol = result_value_field()
    hdl = result_value_field()
    ldl = result_value_field()
    triglycerides = result_value_field()


# Every panel result model, keyed by TestType.code.
PANEL_MODELS = {model.TEST_CODE: model for model in (BMPResult, CBCResult, LipidResult)}
