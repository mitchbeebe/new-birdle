from typing import cast

from django import forms
from django.contrib.auth.models import User

from . import geocode, premium
from .models import Bird, BirdRegion, CustomRegion, Region

NEAR_ME = "Near me"


def user_custom_region(user):
    """The user's built near-me region, or None (anonymous, free, or not built yet)."""
    if user is None or not user.is_authenticated:
        return None
    custom = CustomRegion.objects.filter(user=user, species_count__gt=0).first()
    if custom is None or not premium.is_premium(user):
        return None
    return custom


def practice_pool(user, region, family):
    """BirdRegion rows to practice on. Every near-me region is named "Near me", so that
    choice is resolved to the requesting user's own region rather than matched by name."""
    birdregions = BirdRegion.objects.all()
    if region == NEAR_ME:
        custom = user_custom_region(user)
        birdregions = birdregions.filter(region=custom.region if custom else None)
    elif region != "Any":
        birdregions = birdregions.filter(region__name=region)
    if family != "Any":
        birdregions = birdregions.filter(bird__family=family)
    return birdregions


class BirdRegionForm(forms.Form):
    region = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-control"}))
    family = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-control"}))

    def __init__(self, *args, user=None, **kwargs):
        super(BirdRegionForm, self).__init__(*args, **kwargs)
        self.user = user
        region_field = cast(forms.ChoiceField, self.fields["region"])
        region_field.choices = [
            ("Any", "Any Region"),
            *([(NEAR_ME, NEAR_ME)] if user_custom_region(user) else []),
            *[
                (val[0], val[0])
                for val in Region.objects.exclude(code__startswith="near-me-")
                .values_list("name")
                .order_by("name")
            ],
        ]

        family_field = cast(forms.ChoiceField, self.fields["family"])
        family_field.choices = [
            ("Any", "Any Family"),
            *[
                (val[0], val[0])
                for val in Bird.objects.values_list("family").distinct().order_by("family")
            ],
        ]

    def clean(self):
        cleaned_data = super().clean() or {}
        region = cleaned_data.get("region")
        family = cleaned_data.get("family")

        if not practice_pool(self.user, region, family).exists():
            raise forms.ValidationError(f"{family} have not been found in the {region} region.")

        return cleaned_data


class UsernameForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username"]
        widgets = {"username": forms.TextInput(attrs={"class": "form-control"})}

    def clean_username(self):
        username = self.cleaned_data["username"]
        if username.isdigit():
            raise forms.ValidationError("Username cannot be all digits.")
        return username


class CustomRegionForm(forms.ModelForm):
    """Either a typed place (geocoded server-side) or lat/lng filled by browser geolocation."""

    class Meta:
        model = CustomRegion
        fields = ["location", "lat", "lng"]
        labels = {"location": "Your location"}
        widgets = {
            "location": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "City, address, or place name",
                    "autocomplete": "off",
                }
            ),
            "lat": forms.HiddenInput(),
            "lng": forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lat"].required = False
        self.fields["lng"].required = False

    def clean(self):
        cleaned = super().clean() or {}
        lat, lng = cleaned.get("lat"), cleaned.get("lng")
        location = (cleaned.get("location") or "").strip()
        if lat is not None and lng is not None:
            if not -90 <= lat <= 90 or not -180 <= lng <= 180:
                raise forms.ValidationError("That location is out of range.")
            # Coordinates came from the device; show a place name rather than raw numbers.
            try:
                cleaned["location"] = geocode.reverse_lookup(lat, lng)
            except geocode.GeocodeError:
                cleaned["location"] = ""
            return cleaned
        if not location:
            raise forms.ValidationError("Enter a location or use your device's location.")
        try:
            cleaned["lat"], cleaned["lng"], cleaned["location"] = geocode.lookup(location)
        except geocode.GeocodeError as exc:
            raise forms.ValidationError(str(exc))
        return cleaned
