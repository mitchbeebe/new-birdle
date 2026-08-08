from typing import cast

from allauth.account.forms import LoginForm, ResetPasswordForm, ResetPasswordKeyForm, SignupForm
from django import forms

from .models import Bird, BirdRegion, Region


class BootstrapFormMixin:
    """Adds the Bootstrap `form-control` class to every field, matching BirdRegionForm."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in cast(forms.BaseForm, self).fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class StyledLoginForm(BootstrapFormMixin, LoginForm):
    pass


class StyledSignupForm(BootstrapFormMixin, SignupForm):
    pass


class StyledResetPasswordForm(BootstrapFormMixin, ResetPasswordForm):
    pass


class StyledResetPasswordKeyForm(BootstrapFormMixin, ResetPasswordKeyForm):
    pass


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
