from typing import cast

from allauth.account.forms import LoginForm, ResetPasswordForm, ResetPasswordKeyForm, SignupForm
from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.validators import UnicodeUsernameValidator

from .models import Bird, BirdRegion, Profile, Region


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


class ProfileForm(forms.ModelForm):
    username = forms.CharField(
        max_length=150,
        validators=[UnicodeUsernameValidator()],
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    class Meta:
        model = Profile
        fields = ["bio"]
        widgets = {
            "bio": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["username"].initial = user.username

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.exclude(pk=self.user.pk).filter(username=username).exists():
            raise forms.ValidationError("That username is already taken.")
        return username

    def save(self, commit=True):
        profile = super().save(commit=False)
        self.user.username = self.cleaned_data["username"]
        if commit:
            self.user.save()
            profile.save()
        return profile
