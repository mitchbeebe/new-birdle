from datetime import datetime
from django.core.management.base import BaseCommand
from dotenv import load_dotenv
import os
import requests
from birdle.models import Region, BirdRegion, Bird


class Command(BaseCommand):
    help = "Update bird regions based on recent observations on eBird"

    def handle(self, *args, **options):
        load_dotenv("birdle/.env")
        api_key = os.getenv("EBIRD_API_KEY")
        region_codes = ["lower48", "na", "ca", "sa", "eu", "af", "as", "aut"]

        # Helper function for determining valid observations
        def is_valid(observation, region_code):
            # Exclude all exotic (naturalized, provisional, or escapee) species
            if observation.get("exoticCategory"):
                return False
            # Check lat/long of observation for USA Lower 48
            elif region_code == "lower48":
                lat = observation.get("lat")
                lng = observation.get("lng")
                if lat > 24.5 and lat < 49.5 and lng < -66.5 and lng > -124.5:
                    return True
                else:
                    return False
            # Otherwise assume it's a valid observation for the region
            else:
                return True

        for region_code in region_codes:
            self.stdout.write(f"Beginning update for {region_code}")
            start = datetime.now()
            region = Region.objects.get(code=region_code)

            # Get the countries that make up our regions
            countries = requests.get(
                f"https://api.ebird.org/v2/ref/region/list/country/{region_code}",
                headers={"X-eBirdApiToken": api_key},
            ).json()
            country_code_list = [country.get("code") for country in countries]

            # Observation API accepts up to 10 countries per call, so create chunks of 10
            chunks = [country_code_list[i : i + 10] for i in range(0, len(country_code_list), 10)]

            # Get all currently associated birds with this region
            old_birds_in_region = Bird.objects.filter(birdregion__region__code=region_code)

            # Get all recently observed species from each chunk of countries
            species_codes = []
            for chunk in chunks:
                country_chunk = ",".join(chunk)
                self.stdout.write(f"Fetching observations from {country_chunk}")

                observations = requests.get(
                    f"https://api.ebird.org/v2/data/obs/world/recent?back=30&r={country_chunk}",
                    headers={"X-eBirdApiToken": api_key},
                ).json()

                # Add all non-exotic species to our list
                # "Exotic" defined here https://support.ebird.org/en/support/solutions/articles/48001218430-exotic-and-introduced-species-in-ebird
                species_codes += [
                    observation.get("speciesCode")
                    for observation in observations
                    if is_valid(observation, region_code)
                ]

            new_birds_in_region = Bird.objects.filter(species_code__in=species_codes)

            # Remove birds not seen recently
            birds_to_remove = old_birds_in_region.difference(new_birds_in_region)
            BirdRegion.objects.filter(region=region, bird__in=birds_to_remove.values("id")).delete()

            # Add birds not already in the region
            birds_to_add = new_birds_in_region.difference(old_birds_in_region)
            bulk_birdregions = [BirdRegion(region=region, bird=bird) for bird in birds_to_add]
            _ = BirdRegion.objects.bulk_create(bulk_birdregions)

            # Log the runtime
            elapsed = (datetime.now() - start).seconds
            self.stdout.write(self.style.SUCCESS(f"{region} region updated in {elapsed}s"))
