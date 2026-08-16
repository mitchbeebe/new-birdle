from datetime import date, timedelta

from django.test import TestCase

from .models import Bird, BirdRegion, Game, Region
from .views import random_bird


def make_bird(species_code):
    return Bird.objects.create(
        species_code=species_code,
        name=species_code,
        scientific_name=species_code,
        order="order",
        family="family",
        genus="genus",
        url="https://example.com",
    )


class RandomBirdTests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(code="test-region", name="Test Region")

    def test_excludes_recently_used_birds(self):
        birds = [make_bird(f"bird-{i}") for i in range(3)]
        for bird in birds:
            BirdRegion.objects.create(bird=bird, region=self.region)

        today = date.today()
        Game.objects.create(date=today - timedelta(days=1), bird=birds[0], region=self.region)
        Game.objects.create(date=today - timedelta(days=2), bird=birds[1], region=self.region)

        for _ in range(10):
            self.assertEqual(random_bird(self.region.code), birds[2])

    def test_full_pool_available_with_no_history(self):
        birds = [make_bird(f"bird-{i}") for i in range(3)]
        for bird in birds:
            BirdRegion.objects.create(bird=bird, region=self.region)

        drawn_ids = {random_bird(self.region.code).id for _ in range(30)}
        self.assertEqual(drawn_ids, {bird.id for bird in birds})

    def test_full_cycle_before_repeat(self):
        n = 8
        birds = [make_bird(f"bird-{i}") for i in range(n)]
        for bird in birds:
            BirdRegion.objects.create(bird=bird, region=self.region)

        today = date.today()
        drawn = []
        for i in range(n):
            bird = random_bird(self.region.code)
            drawn.append(bird)
            Game.objects.create(date=today - timedelta(days=n - i), bird=bird, region=self.region)

        self.assertEqual(len({bird.id for bird in drawn}), n)

        next_bird = random_bird(self.region.code)
        self.assertIn(next_bird.id, {bird.id for bird in birds})
