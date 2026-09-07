"""eBird API client for building custom-region species pools."""

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import Bird, BirdRegion

NEARBY_URL = "https://api.ebird.org/v2/data/obs/geo/recent"
CACHE_TIMEOUT = 60 * 60 * 24
# Fixed search window: 50 km radius, 30 days back, reviewed sightings only.
DIST_KM = 50
DAYS_BACK = 30


class EbirdError(Exception):
    pass


def fetch_nearby_species_codes(lat, lng) -> list[str]:
    """Species codes observed recently near (lat, lng). Cached for a day per location."""
    key = f"ebird:nearby:{lat}:{lng}"
    codes = cache.get(key)
    if codes is not None:
        return codes
    if not settings.EBIRD_ENABLED:
        raise EbirdError("eBird isn't configured (EBIRD_API_KEY is unset).")
    params = {
        "lat": str(lat),
        "lng": str(lng),
        "dist": DIST_KM,
        "back": DAYS_BACK,
        "includeProvisional": "false",
    }
    try:
        response = requests.get(
            NEARBY_URL,
            params=params,
            headers={"X-eBirdApiToken": settings.EBIRD_API_KEY},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise EbirdError(f"Couldn't reach eBird: {exc}") from exc
    if response.status_code != 200:
        raise EbirdError(f"eBird returned HTTP {response.status_code}.")
    try:
        codes = sorted({obs["speciesCode"] for obs in response.json()})
    except (ValueError, KeyError, TypeError) as exc:
        raise EbirdError("eBird returned an unexpected response.") from exc
    cache.set(key, codes, timeout=CACHE_TIMEOUT)
    return codes


def build_pool(custom_region) -> int:
    """Fetch nearby species and replace the region's pool with the ones Birdle knows about."""
    codes = fetch_nearby_species_codes(custom_region.lat, custom_region.lng)
    birds = list(Bird.objects.filter(species_code__in=codes))
    with transaction.atomic():
        BirdRegion.objects.filter(region=custom_region.region).delete()
        BirdRegion.objects.bulk_create(
            [BirdRegion(bird=bird, region=custom_region.region) for bird in birds]
        )
        custom_region.species_count = len(birds)
        custom_region.built_at = timezone.now()
        custom_region.save(update_fields=["species_count", "built_at"])
    return len(birds)
