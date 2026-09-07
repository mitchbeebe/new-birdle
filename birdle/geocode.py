"""Forward geocoding via latlng.work, used to turn a typed place into coordinates."""

from decimal import Decimal

import requests
from django.conf import settings

GEOCODE_URL = "https://api.latlng.work/api"


class GeocodeError(Exception):
    pass


def lookup(query: str) -> tuple[Decimal, Decimal, str]:
    """Return (lat, lng, label) for the best match of ``query``."""
    if not settings.LATLNG_API_KEY:
        raise GeocodeError("Location lookup isn't configured (LATLNG_API_KEY is unset).")
    try:
        response = requests.get(
            GEOCODE_URL,
            params={"q": query, "limit": 1},
            headers={"X-Api-Key": settings.LATLNG_API_KEY},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise GeocodeError(f"Couldn't reach the location service: {exc}") from exc
    if response.status_code != 200:
        raise GeocodeError(f"Location service returned HTTP {response.status_code}.")
    try:
        features = response.json()["features"]
    except (ValueError, KeyError, TypeError) as exc:
        raise GeocodeError("Location service returned an unexpected response.") from exc
    if not features:
        raise GeocodeError(f"Couldn't find a place matching '{query}'.")
    feature = features[0]
    lng, lat = feature["geometry"]["coordinates"]
    props = feature.get("properties", {})
    parts = [props.get(k) for k in ("name", "state", "country")]
    label = ", ".join(dict.fromkeys(p for p in parts if p))
    return round(Decimal(str(lat)), 2), round(Decimal(str(lng)), 2), label or query
