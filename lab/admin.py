from django.contrib import admin

from .models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = (
        "last_name",
        "first_name",
        "date_of_birth",
        "phone",
        "insurance_provider",
        "is_active",
    )
    list_filter = ("is_active", "gender")
    search_fields = ("first_name", "last_name", "phone", "insurance_policy_number")
