from django import forms
from .models import Bird, BirdRegion

REGION_CHOICES = [
    ('Any', 'Any Region'),
    *[(val[0], val[0]) for val in BirdRegion.objects.values_list("region_name").distinct().order_by("region_name")]
]

FAMILY_CHOICES = [
    ('Any', 'Any Family'),
    *[(val[0], val[0]) for val in Bird.objects.values_list("family").distinct().order_by("family")]]

class FlashcardForm(forms.Form):
    region = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-control"}),
                               choices=REGION_CHOICES)
    family = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-control"}),
                               choices=FAMILY_CHOICES)
    
    def clean(self):
        cleaned_data = super().clean()
        region = cleaned_data.get('region')
        family = cleaned_data.get('family')
        
        birdregions = BirdRegion.objects.all()
        if region != "Any":
            birdregions = birdregions.filter(region_name=region)
        if family != "Any":
            birdregions = birdregions.filter(bird__family=family)

        if not birdregions.exists():
            raise forms.ValidationError(f"{family} have not been found in the {region} region.")

        return cleaned_data