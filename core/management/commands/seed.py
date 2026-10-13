"""
Load FAKE seed data for LOCAL TESTING ONLY.

Every name, address, phone number, email and insurance number below is made up.
Never run this against a production database.

Usage: python manage.py seed
Safe to run more than once: existing rows are updated, not duplicated.
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import User
from lab.models import Patient

# Shared password for every seeded staff account (stored hashed via set_password).
SEED_PASSWORD = "TestPass123!"

# One account per staff role. Patient and healthcare_provider roles are not seeded.
STAFF_USERS = [
    {"username": "manager1", "role": User.Role.LAB_MANAGER, "first_name": "Maria", "last_name": "Lopez", "is_staff": True},
    {"username": "collector1", "role": User.Role.SPECIMEN_COLLECTOR, "first_name": "Daniel", "last_name": "Kim", "is_staff": False},
    {"username": "tech1", "role": User.Role.TECHNICIAN, "first_name": "Aisha", "last_name": "Patel", "is_staff": False},
    {"username": "pathologist1", "role": User.Role.PATHOLOGIST, "first_name": "Robert", "last_name": "Chen", "is_staff": False},
    {"username": "cashier1", "role": User.Role.CASHIER, "first_name": "Emily", "last_name": "Johnson", "is_staff": False},
]

# Fake patients. Matched on (first_name, last_name, date_of_birth) when re-seeding.
PATIENTS = [
    {"first_name": "James", "last_name": "Anderson", "date_of_birth": date(1985, 3, 14), "gender": Patient.Gender.MALE,
     "address": "1204 E Speedway Blvd, Tucson, AZ 85719", "phone": "520-555-0101", "email": "james.anderson@example.com",
     "insurance_provider": "Blue Cross Blue Shield", "insurance_policy_number": "BCBS-100234", "is_active": True},
    {"first_name": "Sofia", "last_name": "Martinez", "date_of_birth": date(1992, 7, 2), "gender": Patient.Gender.FEMALE,
     "address": "88 N Campbell Ave, Tucson, AZ 85705", "phone": "520-555-0102", "email": "sofia.martinez@example.com",
     "insurance_provider": "Aetna", "insurance_policy_number": "AET-558812", "is_active": True},
    {"first_name": "Michael", "last_name": "Brown", "date_of_birth": date(1970, 11, 23), "gender": Patient.Gender.MALE,
     "address": "450 W Grant Rd, Tucson, AZ 85705", "phone": "520-555-0103", "email": "",
     "insurance_provider": "UnitedHealthcare", "insurance_policy_number": "UHC-772019", "is_active": True},
    {"first_name": "Olivia", "last_name": "Nguyen", "date_of_birth": date(2001, 1, 30), "gender": Patient.Gender.FEMALE,
     "address": "3301 E Broadway Blvd, Tucson, AZ 85716", "phone": "520-555-0104", "email": "olivia.nguyen@example.com",
     "insurance_provider": "Cigna", "insurance_policy_number": "CIG-330945", "is_active": True},
    {"first_name": "Alex", "last_name": "Rivera", "date_of_birth": date(1998, 5, 9), "gender": Patient.Gender.OTHER,
     "address": "742 S 4th Ave, Tucson, AZ 85701", "phone": "520-555-0105", "email": "alex.rivera@example.com",
     "insurance_provider": "Humana", "insurance_policy_number": "HUM-610284", "is_active": True},
    {"first_name": "Linda", "last_name": "Thompson", "date_of_birth": date(1958, 9, 17), "gender": Patient.Gender.FEMALE,
     "address": "15 E Congress St, Tucson, AZ 85701", "phone": "520-555-0106", "email": "",
     "insurance_provider": "Medicare", "insurance_policy_number": "MCR-1EG4TE5MK72", "is_active": True},
    {"first_name": "David", "last_name": "Wilson", "date_of_birth": date(1979, 12, 5), "gender": Patient.Gender.MALE,
     "address": "2900 N Oracle Rd, Tucson, AZ 85705", "phone": "520-555-0107", "email": "david.wilson@example.com",
     "insurance_provider": "Blue Cross Blue Shield", "insurance_policy_number": "BCBS-100877", "is_active": False},
    {"first_name": "Grace", "last_name": "Okafor", "date_of_birth": date(1988, 4, 21), "gender": Patient.Gender.FEMALE,
     "address": "610 E 6th St, Tucson, AZ 85705", "phone": "520-555-0108", "email": "grace.okafor@example.com",
     "insurance_provider": "AHCCCS", "insurance_policy_number": "AHC-A12345678", "is_active": True},
    {"first_name": "Taylor", "last_name": "Reed", "date_of_birth": date(2005, 8, 12), "gender": Patient.Gender.UNKNOWN,
     "address": "1717 E Fort Lowell Rd, Tucson, AZ 85719", "phone": "520-555-0109", "email": "taylor.reed@example.com",
     "insurance_provider": "Aetna", "insurance_policy_number": "AET-559031", "is_active": True},
    {"first_name": "Carlos", "last_name": "Garcia", "date_of_birth": date(1965, 2, 28), "gender": Patient.Gender.MALE,
     "address": "5100 E Grant Rd, Tucson, AZ 85712", "phone": "520-555-0110", "email": "carlos.garcia@example.com",
     "insurance_provider": "UnitedHealthcare", "insurance_policy_number": "UHC-773560", "is_active": True},
]


class Command(BaseCommand):
    help = "Load FAKE seed data (staff users and patients) for local testing only."

    @transaction.atomic
    def handle(self, *args, **options):
        users_created = 0
        for data in STAFF_USERS:
            username = data["username"]
            user, created = User.objects.update_or_create(
                username=username,
                defaults={
                    "role": data["role"],
                    "first_name": data["first_name"],
                    "last_name": data["last_name"],
                    "email": f"{username}@example.com",
                    "is_staff": data["is_staff"],
                    "must_change_password": False,
                },
            )
            # Always (re)set the known password so the team can log in after re-seeding.
            user.set_password(SEED_PASSWORD)
            user.save(update_fields=["password"])
            users_created += created

        patients_created = 0
        for data in PATIENTS:
            lookup = {key: data[key] for key in ("first_name", "last_name", "date_of_birth")}
            defaults = {key: value for key, value in data.items() if key not in lookup}
            _, created = Patient.objects.update_or_create(**lookup, defaults=defaults)
            patients_created += created

        self.stdout.write(self.style.SUCCESS(
            f"Seed complete: {len(STAFF_USERS)} users, {len(PATIENTS)} patients "
            f"({users_created} users and {patients_created} patients newly created)"
        ))
