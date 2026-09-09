"""Forward geocoding via latlng.work, used to turn a typed place into coordinates."""

from decimal import Decimal

import requests
from django.conf import settings

GEOCODE_URL = "https://api.latlng.work/api"
REVERSE_URL = "https://api.latlng.work/reverse"


class GeocodeError(Exception):
    pass


def _features(url, params) -> list:
    if not settings.LATLNG_API_KEY:
        raise GeocodeError("Location lookup isn't configured (LATLNG_API_KEY is unset).")
    try:
        response = requests.get(
            url, params=params, headers={"X-Api-Key": settings.LATLNG_API_KEY}, timeout=10
        )
    except requests.RequestException as exc:
        raise GeocodeError(f"Couldn't reach the location service: {exc}") from exc
    if response.status_code != 200:
        raise GeocodeError(f"Location service returned HTTP {response.status_code}.")
    try:
        return response.json()["features"]
    except (ValueError, KeyError, TypeError) as exc:
        raise GeocodeError("Location service returned an unexpected response.") from exc


def _label(props: dict, *keys: str) -> str:
    """Join the first-present values of ``keys``, dropping duplicates, e.g. "Portland, OR"."""
    return ", ".join(dict.fromkeys(v for v in (props.get(k) for k in keys) if v))


def lookup(query: str) -> tuple[Decimal, Decimal, str]:
    """Return (lat, lng, label) for the best match of ``query``."""
    features = _features(GEOCODE_URL, {"q": query, "limit": 1})
    if not features:
        raise GeocodeError(f"Couldn't find a place matching '{query}'.")
    feature = features[0]
    lng, lat = feature["geometry"]["coordinates"]
    label = _label(feature.get("properties", {}), "name", "state", "country")
    return round(Decimal(str(lat)), 2), round(Decimal(str(lng)), 2), label or query


def reverse_lookup(lat, lng) -> str:
    """A friendly place name for coordinates ("Portland, OR"), or "" if none is known."""
    features = _features(REVERSE_URL, {"lat": str(lat), "lon": str(lng)})
    if not features:
        return ""
    props = features[0].get("properties", {})
    return _label(props, "city", "state", "country") or _label(props, "name", "state", "country")
