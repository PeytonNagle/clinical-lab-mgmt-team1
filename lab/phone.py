import re

import phonenumbers
from django import forms
from django.core.exceptions import ValidationError

# Digits and the usual separators only. This keeps out letters (the library would turn them into digits) and extensions.
_READABLE = re.compile(r"\A\+?[0-9\s().-]+\Z")

_ERROR = "Enter a valid phone number like 520-555-0101. For a number outside the US, start with + and the country code."


def phone_digits(text):
    """The digits of text typed like a phone number, or "" if it has any other characters."""
    return re.sub(r"[^0-9]", "", text) if _READABLE.match(text) else ""


def normalize_phone(value):
    """Return a real number as 520-555-0101 (US is assumed) or +<digits> for another country; raise if not."""
    value = value.strip()
    if not phone_digits(value):
        raise ValidationError(_ERROR)
    try:
        number = phonenumbers.parse(value, "US")
    except phonenumbers.NumberParseException:
        raise ValidationError(_ERROR)
    if not phonenumbers.is_valid_number(number):
        raise ValidationError(_ERROR)
    if number.country_code == 1:
        digits = str(number.national_number)
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


class PhoneField(forms.CharField):
    """A phone box that accepts several layouts and saves the recommended one."""

    def to_python(self, value):
        value = super().to_python(value)
        return normalize_phone(value) if value else value
