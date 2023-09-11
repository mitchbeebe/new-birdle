from django.db import models
from django.conf import settings

class Bird(models.Model):
    species_code = models.CharField(max_length=100)
    name = models.CharField(max_length=100)
    scientific_name = models.CharField(max_length=100)
    order = models.CharField(max_length=100)
    family = models.CharField(max_length=100)
    genus = models.CharField(max_length=100)
    url = models.URLField()

    def __str__(self):
        return self.name
    
    def __eq__(self, other):
        if not isinstance(other, Bird):
            return False
        return self.scientific_name == other.scientific_name
    
    def compare(self, other):
        if not isinstance(other, Bird):
            return False
        return [self.order == other.order, 
                self.family == other.family, 
                self.genus == other.genus, 
                self.scientific_name == other.scientific_name]
    
    def taxonomy(self):
        return {
            'order': self.order,
            'family': self.family,
            'genus': self.genus,
            'name': self.name
        }
    
    def info(self):
        return {
            'species_code': self.species_code,
            'name': self.name,
            'url': self.url
        }


class Game(models.Model):
    date = models.DateField()
    bird = models.ForeignKey(Bird, on_delete=models.CASCADE, null=True)

    def __str__(self):
        return f"{self.date}: {self.bird}"


class Guess(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    game = models.ForeignKey(Game, on_delete=models.CASCADE, null=True)
    bird = models.ForeignKey(Bird, on_delete=models.CASCADE, null=True)
    guessed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Guesses"


class Image(models.Model):
    url = models.URLField()
    label = models.CharField(max_length=100)
    bird = models.ForeignKey(Bird, on_delete=models.CASCADE, null=True)