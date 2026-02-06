from typing import cast

from django import forms

from .models import Bird, BirdRegion, Region


class BirdRegionForm(forms.Form):
    region = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-control"}))
    family = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-control"}))

    def __init__(self, *args, **kwargs):
        super(BirdRegionForm, self).__init__(*args, **kwargs)
        region_field = cast(forms.ChoiceField, self.fields["region"])
        region_field.choices = [
            ("Any", "Any Region"),
            *[(val[0], val[0]) for val in Region.objects.values_list("name").order_by("name")],
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
