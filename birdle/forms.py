from django import forms
from .models import Bird

FAMILY_CHOICES=[('Any', 'Any'), *[(val[0], val[0]) for val in Bird.objects.values_list("family").distinct()]]

class FlashcardForm(forms.Form):
    family = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-control"}),
                               choices=FAMILY_CHOICES)