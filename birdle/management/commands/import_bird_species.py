# import_bird_species.py

import csv
from django.core.management.base import BaseCommand
from birdle.models import Bird


class Command(BaseCommand):
    help = "Import bird species from eBird Taxonomy v2022 dataset"

    def handle(self, *args, **options):
        # Open the CSV file and create a CSV reader
        with open("birdle/static/birdle/ebird_taxonomy_v2022.csv") as csvfile:
            reader = csv.reader(csvfile)

            # Skip the header row
            next(reader)

            # Loop through each row in the CSV file
            for row in reader:
                # Extract the fields from the row
                category, species_code, name, scientific_name, order, family, genus = (
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                    row[5],
                    row[6],
                    row[4].split(" ")[0],
                )
                url = "https://ebird.org/species/" + row[2]

                # Create the Bird object if it doesn't already exist
                if category == "species" and not Bird.objects.filter(name=name).exists():
                    bird, _ = Bird.objects.update_or_create(
                        species_code=species_code,
                        name=name,
                        scientific_name=scientific_name,
                        order=order,
                        family=family,
                        genus=genus,
                        defaults={"url": url},
                    )
                    self.stdout.write(self.style.SUCCESS(f"Created bird: {bird}"))
