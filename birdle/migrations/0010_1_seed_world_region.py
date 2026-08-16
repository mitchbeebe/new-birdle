from django.db import migrations


def seed_world_region(apps, schema_editor):
    Region = apps.get_model("birdle", "Region")
    Region.objects.get_or_create(name="World", defaults={"code": "world"})


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("birdle", "0010_region_remove_birdregion_region_code_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_world_region, noop),
    ]
