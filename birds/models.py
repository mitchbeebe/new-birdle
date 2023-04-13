from django.db import models

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


class Guess(models.Model):
    game_date = models.DateField(auto_now_add=True)
    user_id = models.CharField(max_length=100)
    species_code = models.CharField(max_length=100)
    guessed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.species_code