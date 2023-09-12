# populate_games.py

import csv
from django.core.management.base import BaseCommand
from birdle.models import Bird, Game
import random
from datetime import date, timedelta

class Command(BaseCommand):
    help = 'Populate Games data with date and bird'

    def handle(self, *args, **options):
        # TODO
        bird_ids = list(Bird.objects.values_list('id', flat=True))
        random.shuffle(bird_ids)

        start_date = date(2023,9,11)
        num_birds = len(bird_ids)
        date_list = [start_date + timedelta(days=i) for i in range(num_birds)]

        for game_date, bird_id in zip(date_list, bird_ids):
            game = Game.objects.create(
                date=game_date,
                bird_id=bird_id
            )
            self.stdout.write(self.style.SUCCESS(f'Created game - {game}'))
