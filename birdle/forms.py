from typing import cast

from django import forms
from django.contrib.auth.models import User

from .models import Bird, BirdRegion, CustomRegion, Region


class BirdRegionForm(forms.Form):
    region = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-control"}))
    family = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-control"}))

    def __init__(self, *args, **kwargs):
        super(BirdRegionForm, self).__init__(*args, **kwargs)
        region_field = cast(forms.ChoiceField, self.fields["region"])
        region_field.choices = [
            ("Any", "Any Region"),
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

        birdregions = BirdRegion.objects.all()
        if region != "Any":
            birdregions = birdregions.filter(region__name=region)
        if family != "Any":
            birdregions = birdregions.filter(bird__family=family)

        if not birdregions.exists():
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
    class Meta:
        model = CustomRegion
        fields = ["lat", "lng"]
        labels = {
            "lat": "Latitude",
            "lng": "Longitude",
        }
        widgets = {
            "lat": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "lng": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }

    def clean_lat(self):
        lat = self.cleaned_data["lat"]
        if not -90 <= lat <= 90:
            raise forms.ValidationError("Latitude must be between -90 and 90.")
        return lat

    def clean_lng(self):
        lng = self.cleaned_data["lng"]
        if not -180 <= lng <= 180:
            raise forms.ValidationError("Longitude must be between -180 and 180.")
        return lng
