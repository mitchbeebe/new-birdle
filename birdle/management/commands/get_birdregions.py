# import_bird_species.py

import requests
from dotenv import load_dotenv
import os
from django.core.management.base import BaseCommand
from birdle.models import Bird, BirdRegion, Region


class Command(BaseCommand):
    help = "Import Regions"

    def handle(self, *args, **options):
        load_dotenv("birdle/.env")
        api_key = os.getenv("EBIRD_API_KEY")
        regions = Region.objects.all()

        for region in regions:
            r = requests.get(
                f"https://api.ebird.org/v2/product/spplist/{region.code}",
                headers={"X-eBirdApiToken": api_key},
            )

            species_codes = r.json()

            for species_code in species_codes:
                try:
                    bird = Bird.objects.get(species_code=species_code)
                except Bird.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f"{species_code} does not exist"))
                else:
                    bird_region, _ = BirdRegion.objects.update_or_create(bird=bird, region=region)
                    self.stdout.write(self.style.SUCCESS(f"Created bird region: {bird_region}"))
