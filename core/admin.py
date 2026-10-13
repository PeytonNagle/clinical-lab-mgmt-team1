from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


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
