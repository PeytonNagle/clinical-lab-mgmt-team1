import django.core.validators
from django.db import migrations, models

policy_number_validator = django.core.validators.RegexValidator(
    r"\A[A-Za-z0-9-]+\Z", "Use letters, numbers and hyphens only."
)


def copy_insurance_from_patient(apps, schema_editor):
    TestOrder = apps.get_model("lab", "TestOrder")
    for order in TestOrder.objects.select_related("patient"):
        order.insurance_provider = order.patient.insurance_provider
        order.insurance_policy_number = order.patient.insurance_policy_number
        order.save(update_fields=["insurance_provider", "insurance_policy_number"])


class Migration(migrations.Migration):

    dependencies = [
        ('lab', '0003_seed_test_types'),
    ]

    operations = [
        # The default only fills existing rows; the data step below replaces it with the patient's values.
        migrations.AddField(
            model_name='testorder',
            name='insurance_provider',
            field=models.CharField(default='', max_length=100),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='testorder',
            name='insurance_policy_number',
            field=models.CharField(default='', max_length=50, validators=[policy_number_validator]),
            preserve_default=False,
        ),
        migrations.RunPython(copy_insurance_from_patient, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='patient',
            name='insurance_policy_number',
            field=models.CharField(max_length=50, validators=[policy_number_validator]),
        ),
    ]
