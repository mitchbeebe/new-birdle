# Generated by Django 5.0.1 on 2024-03-12 19:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('birdle', '0008_guess_hint_used'),
    ]

    operations = [
        migrations.AlterField(
            model_name='guess',
            name='hint_used',
            field=models.BooleanField(default=False, null=True),
        ),
    ]
