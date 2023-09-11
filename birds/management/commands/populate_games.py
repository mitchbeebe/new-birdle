# populate_games.py

import csv
from django.core.management.base import BaseCommand
from birds.models import Bird, Game
import random
from datetime import date, timedelta

class Command(BaseCommand):
    help = 'Import bird species from eBird Taxonomy v2022 dataset'

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
        # # Open the CSV file and create a CSV reader
        # with open('birds/static/birds/ebird_taxonomy_v2022.csv') as csvfile:
        #     reader = csv.reader(csvfile)

        #     # Skip the header row
        #     next(reader)

        #     # Loop through each row in the CSV file
        #     for row in reader:
        #         # Extract the fields from the row
        #         category, species_code, name, scientific_name, order, family, genus = row[1], row[2], row[3], row[4], row[5], row[6], row[4].split(' ')[0]
        #         url = "https://ebird.org/species/" + row[2] #'https://search.macaulaylibrary.org/catalog?taxonCode=' + row[2]

        #         # Create the Bird object if it doesn't already exist
        #         if category == 'species' and not Bird.objects.filter(name=name).exists():
        #             bird = Bird.objects.create(
        #                 species_code=species_code,
        #                 name=name,
        #                 scientific_name=scientific_name,
        #                 order=order, 
        #                 family=family, 
        #                 genus=genus,
        #                 url=url)
        #             self.stdout.write(self.style.SUCCESS(f'Created bird: {bird}'))
