import re

from django import forms
from django.core.exceptions import ValidationError

# Digits plus the usual separators; a leading + marks a country code.
_READABLE = re.compile(r"\A\+?[\d\s().-]+\Z")

ERROR = "Enter a 10-digit US phone number like 520-555-0101, or start with + and the country code."


def normalize_phone(value):
    """Return the number as 520-555-0101 (US is assumed) or +<digits> for another country; raise if unreadable."""
    value = value.strip()
    if not _READABLE.match(value):
        raise ValidationError(ERROR)
    digits = re.sub(r"\D", "", value)
    plus = value.startswith("+")
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    elif plus and 8 <= len(digits) <= 15 and digits[0] != "1":
        return "+" + digits
    elif plus:
        # Country code 1 is the US, so it needs exactly 11 digits.
        raise ValidationError(ERROR)
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    raise ValidationError(ERROR)


class PhoneField(forms.CharField):
    """A phone box that accepts several layouts and saves the recommended one."""

    def to_python(self, value):
        value = super().to_python(value)
        return normalize_phone(value) if value else value
