from django.db import migrations

# The supplies every lab install starts with, and how many units one run of each test uses.
# Not fake data (no stock is added), so it lives in a migration and not in `seed`.
SUPPLY_ITEMS = [
    ("Serum separator tube (gold top)", "tubes"),
    ("EDTA tube (lavender top)", "tubes"),
    ("BMP reagent cartridge", "tests"),
    ("Lipid panel reagent cartridge", "tests"),
    ("Hematology reagent pack", "tests"),
    ("Pipette tips", "tips"),
]

TEST_SUPPLIES = {
    "BMP": [("Serum separator tube (gold top)", 1), ("BMP reagent cartridge", 1), ("Pipette tips", 2)],
    "CBC": [("EDTA tube (lavender top)", 1), ("Hematology reagent pack", 1)],
    "LIPID": [("Serum separator tube (gold top)", 1), ("Lipid panel reagent cartridge", 1), ("Pipette tips", 2)],
}


def add_test_supplies(apps, schema_editor):
    SupplyItem = apps.get_model("inventory", "SupplyItem")
    TestSupply = apps.get_model("inventory", "TestSupply")
    TestType = apps.get_model("lab", "TestType")

    items = {}
    for name, unit in SUPPLY_ITEMS:
        items[name], _ = SupplyItem.objects.get_or_create(name=name, is_active=True, defaults={"unit": unit})
    for code, needs in TEST_SUPPLIES.items():
        test_type = TestType.objects.filter(code=code).first()
        if test_type is None:
            continue
        for name, quantity in needs:
            TestSupply.objects.update_or_create(
                test_type=test_type, item=items[name], defaults={"quantity": quantity}
            )


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0001_initial'),
        ('lab', '0003_seed_test_types'),
    ]

    operations = [
        # Going backwards keeps the rows: lots may already point at them.
        migrations.RunPython(add_test_supplies, migrations.RunPython.noop),
    ]
