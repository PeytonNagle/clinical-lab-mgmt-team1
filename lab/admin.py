from django.contrib import admin

from .models import BMPResult, CBCResult, LipidResult, Patient, TestOrder, TestType


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


@admin.register(TestType)
class TestTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(TestOrder)
class TestOrderAdmin(admin.ModelAdmin):
    list_display = ("id", "patient", "source", "status", "created_at")
    list_filter = ("status", "source")
    search_fields = (
        "patient__last_name",
        "patient__first_name",
        "physician_name",
        "physician_license_id",
    )
    filter_horizontal = ("tests",)
    readonly_fields = ("created_at",)


@admin.register(BMPResult, CBCResult, LipidResult)
class PanelResultAdmin(admin.ModelAdmin):
    list_display = ("order", "performed_by", "measured_at", "received_at")
    search_fields = ("order__id", "order__patient__last_name", "order__patient__first_name")
    readonly_fields = ("received_at",)
