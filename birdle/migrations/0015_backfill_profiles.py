from django.conf import settings
from django.db import migrations


def create_missing_profiles(apps, schema_editor):
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(app_label, model_name)
    Profile = apps.get_model("birdle", "Profile")
    for user in User.objects.filter(profile__isnull=True):
        Profile.objects.create(user=user)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("birdle", "0014_profile"),
    ]

    operations = [
        migrations.RunPython(create_missing_profiles, noop),
    ]
