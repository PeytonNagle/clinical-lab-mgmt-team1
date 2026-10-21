from django.db import migrations

# The catalog every lab install starts with. Not fake data, so it lives in a migration and not in `seed`.
TEST_TYPES = [
    ("BMP", "Basic metabolic panel"),
    ("CBC", "Complete blood count"),
    ("LIPID", "Lipid panel"),
]


def add_test_types(apps, schema_editor):
    TestType = apps.get_model("lab", "TestType")
    for code, name in TEST_TYPES:
        TestType.objects.update_or_create(code=code, defaults={"name": name})


class Migration(migrations.Migration):

    dependencies = [
        ('lab', '0002_add_test_type_and_order'),
    ]

    operations = [
        # Going backwards keeps the rows: orders may already point at them.
        migrations.RunPython(add_test_types, migrations.RunPython.noop),
    ]
