import random
from django.db import models
from django.conf import settings
from django.contrib.auth.models import User


class Bird(models.Model):
    species_code = models.CharField(unique=True, max_length=100)
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
    
    def info(self):
        return {k: v for k,v in vars(self).items() if k != "_state"}
    
    @classmethod
    def get_random_bird(cls):
        bird_count = cls.objects.count()
        idx = random.randrange(0, bird_count)
        return cls.objects.get(id=idx)
    
    def get_images(self):
        #TODO
        pass


class Region(models.Model):
    code = models.CharField(unique=True, max_length=100)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name
    
    @classmethod
    def get_default_pk(cls):
        region = cls.objects.get(name="World")
        return region.pk


class BirdRegion(models.Model):
    bird = models.ForeignKey(Bird, on_delete=models.CASCADE)
    region = models.ForeignKey(Region, null=True, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.region.name}: {self.bird.name}"


class Game(models.Model):
    date = models.DateField()
    bird = models.ForeignKey(Bird, on_delete=models.CASCADE)
    region = models.ForeignKey(Region, default=Region.get_default_pk, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('date', 'region')

    def __str__(self):
        return f"{self.date}: {self.bird}"
    
    @property
    def img_count(self):
        return Image.objects.filter(bird=self.bird).count()


class UserGame(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    game = models.ForeignKey(Game, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.game.date}: {self.user}"
    
    @property
    def guess_count(self):
        return Guess.objects.filter(usergame=self).count()
    
    @property
    def is_winner(self):
        guesses = Guess.objects.filter(usergame=self)
        return any([guess.is_winner for guess in guesses])


class Guess(models.Model):
    usergame = models.ForeignKey(UserGame, on_delete=models.CASCADE)
    bird = models.ForeignKey(Bird, on_delete=models.CASCADE)
    guessed_at = models.DateTimeField(auto_now_add=True)
    hint_used = models.BooleanField(null=True, default=False)

    class Meta:
        verbose_name_plural = "Guesses"

    def __str__(self):
        return f"{self.usergame.user} {self.bird} {self.guessed_at}"

    @property
    def is_winner(self):
        return self.bird == self.usergame.game.bird


class Image(models.Model):
    url = models.URLField()
    label = models.CharField(max_length=100)
    photographer = models.CharField(null=True, max_length=256)
    bird = models.ForeignKey(Bird, on_delete=models.CASCADE)
