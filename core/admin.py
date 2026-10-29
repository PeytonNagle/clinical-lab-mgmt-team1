from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import ActivityLog, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    # Edit page: Django's default sections plus our custom fields.
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Lab role", {"fields": ("role", "must_change_password")}),
    )
    # Add-user page: Django's default fields (username, passwords) plus role.
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Lab role", {"fields": ("role",)}),
    )
    list_display = ("username", "first_name", "last_name", "role", "is_active")
    list_filter = ("role", "is_active")


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "action", "patient")
    list_filter = ("action",)
    search_fields = ("details",)
    # History is view-only: every field is read-only and entries can't be added or edited here.
    readonly_fields = ("user", "patient", "action", "details", "timestamp")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
