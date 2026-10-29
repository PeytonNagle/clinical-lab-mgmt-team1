from django.core.exceptions import ValidationError
from django.db import migrations

from lab.phone import normalize_phone


def clean_phone_numbers(apps, schema_editor):
    """Rewrite stored numbers in the recommended format. A number that can't be read is left as it is."""
    for model, field in (("Patient", "phone"), ("TestOrder", "physician_phone")):
        Model = apps.get_model("lab", model)
        for row in Model.objects.exclude(**{field: ""}):
            old = getattr(row, field)
            try:
                cleaned = normalize_phone(old)
            except ValidationError:
                continue
            if cleaned != old:
                setattr(row, field, cleaned)
                row.save(update_fields=[field])


class Migration(migrations.Migration):

    dependencies = [
        ('lab', '0004_add_order_insurance'),
    ]

    operations = [
        migrations.RunPython(clean_phone_numbers, migrations.RunPython.noop),
    ]
