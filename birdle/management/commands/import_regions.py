# import_bird_species.py

import requests
import json
from dotenv import load_dotenv
import os
from django.core.management.base import BaseCommand
from birdle.models import Bird, BirdRegion, Region

class Command(BaseCommand):
    help = 'Import Regions'

    def handle(self, *args, **options):
        with open("birdle/static/birdle/regions.json") as file:
            regions = json.load(file)

        for region_name, region_code in regions.items():
            region, _ = Region.objects.get_or_create(name=region_name, code=region_code)
            self.stdout.write(self.style.SUCCESS(f"Created region: {region}"))
