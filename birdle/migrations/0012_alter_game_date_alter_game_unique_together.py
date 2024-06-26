# Generated by Django 5.0.1 on 2024-04-02 02:37

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('birdle', '0011_game_region'),
    ]

    operations = [
        migrations.AlterField(
            model_name='game',
            name='date',
            field=models.DateField(),
        ),
        migrations.AlterUniqueTogether(
            name='game',
            unique_together={('date', 'region')},
        ),
    ]
