from datetime import date

import django.test.client
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Bird, Game, Region, UserGame

# Work around a Django 5.0 / Python 3.14 incompatibility: the test client's
# `store_rendered_templates` does `copy(super())` on the RequestContext used to render a
# response (e.g. allauth's signup flow), which raises AttributeError on this Python version.
# We don't use `assertTemplateUsed`, so it's safe to no-op.
setattr(django.test.client, "store_rendered_templates", lambda *args, **kwargs: None)


class LoginMergeTests(TestCase):
    def setUp(self):
        self.region, _ = Region.objects.get_or_create(code="world", defaults={"name": "World"})
        self.bird = Bird.objects.create(
            species_code="amecro",
            name="American Crow",
            scientific_name="Corvus brachyrhynchos",
            order="Passeriformes",
            family="Corvidae",
            genus="Corvus",
            url="https://example.com/amecro",
        )
        self.game = Game.objects.create(date=date.today(), bird=self.bird, region=self.region)

    def _play_anonymously(self, username):
        anon_user = User.objects.create(username=username)
        UserGame.objects.create(user=anon_user, game=self.game)
        session = self.client.session
        session["username"] = username
        session.save()
        return anon_user

    def test_signup_merges_anonymous_history(self):
        self._play_anonymously("111")

        response = self.client.post(
            reverse("account_signup"),
            {
                "email": "new-player@example.com",
                "password1": "a-strong-password-1",
                "password2": "a-strong-password-1",
            },
        )
        self.assertEqual(response.status_code, 302)

        new_user = User.objects.get(email="new-player@example.com")
        self.assertFalse(User.objects.filter(username="111").exists())
        self.assertTrue(UserGame.objects.filter(user=new_user, game=self.game).exists())

    def test_login_merges_anonymous_history_and_handles_collision(self):
        self._play_anonymously("222")

        existing_user = User.objects.create_user(
            username="existing", password="a-strong-password-2"
        )
        # `existing_user` already has history for today's game, which should collide
        # with the anonymous user's `UserGame` for the same game.
        UserGame.objects.create(user=existing_user, game=self.game)

        logged_in = self.client.login(username="existing", password="a-strong-password-2")
        self.assertTrue(logged_in)

        self.assertFalse(User.objects.filter(username="222").exists())
        self.assertEqual(UserGame.objects.filter(user=existing_user, game=self.game).count(), 1)
