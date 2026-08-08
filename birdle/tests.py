from datetime import date

import django.test.client
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Bird, Friendship, Game, Profile, Region, UserGame

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


class ProfileSignalTests(TestCase):
    def test_profile_created_on_user_creation(self):
        user = User.objects.create_user(username="finch")
        self.assertTrue(Profile.objects.filter(user=user).exists())


class ProfileViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="finch", password="hunter2")

    def test_requires_login(self):
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 302)

    def test_get_shows_current_username_and_bio(self):
        profile = Profile.objects.get(user=self.user)
        profile.bio = "I like birds."
        profile.save()
        self.client.force_login(self.user)

        response = self.client.get(reverse("profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "finch")
        self.assertContains(response, "I like birds.")

    def test_post_updates_username_and_bio(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("profile"), {"username": "sparrow", "bio": "Now a sparrow."}
        )

        self.assertRedirects(response, reverse("profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "sparrow")
        self.assertEqual(Profile.objects.get(user=self.user).bio, "Now a sparrow.")

    def test_post_rejects_duplicate_username(self):
        User.objects.create_user(username="sparrow")
        self.client.force_login(self.user)

        response = self.client.post(reverse("profile"), {"username": "sparrow", "bio": ""})

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "finch")
        self.assertContains(response, "already taken")


class FriendshipTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user(username="alice", password="password123")
        self.bob = User.objects.create_user(username="bob", password="password123")
        self.anon = User.objects.create(username="1234567890")  # password="" (anonymous)

    def test_search_excludes_self_and_anonymous_accounts(self):
        self.client.force_login(self.alice)
        response = self.client.get(reverse("friend_search"), {"q": ""})
        self.assertEqual(list(response.context["results"]), [])

        response = self.client.get(reverse("friend_search"), {"q": "b"})
        self.assertEqual(list(response.context["results"]), [self.bob])

        response = self.client.get(reverse("friend_search"), {"q": "1234"})
        self.assertEqual(list(response.context["results"]), [])

        response = self.client.get(reverse("friend_search"), {"q": "alice"})
        self.assertEqual(list(response.context["results"]), [])

    def test_send_friend_request_creates_pending_friendship(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("send_friend_request", args=[self.bob.username]))

        friendship = Friendship.objects.get(from_user=self.alice, to_user=self.bob)
        self.assertEqual(friendship.status, Friendship.PENDING)

    def test_send_friend_request_to_self_is_rejected(self):
        self.client.force_login(self.alice)
        response = self.client.post(reverse("send_friend_request", args=[self.alice.username]))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Friendship.objects.exists())

    def test_accept_friend_request_updates_status(self):
        friendship = Friendship.objects.create(from_user=self.alice, to_user=self.bob)

        self.client.force_login(self.bob)
        self.client.post(reverse("accept_friend_request", args=[friendship.pk]))

        friendship.refresh_from_db()
        self.assertEqual(friendship.status, Friendship.ACCEPTED)

    def test_only_addressee_can_accept_friend_request(self):
        friendship = Friendship.objects.create(from_user=self.alice, to_user=self.bob)

        self.client.force_login(self.alice)
        response = self.client.post(reverse("accept_friend_request", args=[friendship.pk]))

        self.assertEqual(response.status_code, 404)
        friendship.refresh_from_db()
        self.assertEqual(friendship.status, Friendship.PENDING)

    def test_friends_page_lists_accepted_friends_and_pending_requests(self):
        Friendship.objects.create(
            from_user=self.alice, to_user=self.bob, status=Friendship.ACCEPTED
        )
        Friendship.objects.create(from_user=self.anon, to_user=self.alice)

        self.client.force_login(self.alice)
        response = self.client.get(reverse("friends"))

        self.assertEqual(response.context["friends"], [self.bob])
        self.assertEqual(
            list(response.context["pending_received"]),
            [Friendship.objects.get(from_user=self.anon, to_user=self.alice)],
        )

    def test_friends_page_requires_login(self):
        response = self.client.get(reverse("friends"))
        self.assertEqual(response.status_code, 302)
