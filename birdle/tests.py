from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings

from .models import Bird, BirdRegion, Game, Guess, Region, UserGame
from .signals import merge_anonymous_history
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


# The manifest static storage needs a collectstatic run; plain storage lets pages render in tests.
plain_static_storage = override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)


class AccountsTestMixin:
    def make_game(self, region, day):
        return Game.objects.create(date=day, bird=make_bird(f"bird-{day}"), region=region)


@plain_static_storage
class AnonymousMergeTests(AccountsTestMixin, TestCase):
    def setUp(self):
        self.region, _ = Region.objects.get_or_create(code="world", defaults={"name": "World"})
        self.account = User.objects.create_user("alice", "alice@example.com", "s3cret-pass")
        self.anon = User.objects.create(username="170000000000")
        self.session = self.client.session
        self.session["username"] = self.anon.username
        self.session.save()

    def request_with_session(self):
        request = RequestFactory().get("/")
        request.session = self.session
        return request

    def test_history_moves_to_account_and_anon_deleted(self):
        game = self.make_game(self.region, date(2024, 1, 1))
        usergame = UserGame.objects.create(user=self.anon, game=game)
        Guess.objects.create(usergame=usergame, bird=game.bird)

        merge_anonymous_history(self.request_with_session(), self.account)

        usergame.refresh_from_db()
        self.assertEqual(usergame.user, self.account)
        self.assertEqual(usergame.guess_count, 1)
        self.assertFalse(User.objects.filter(username=self.anon.username).exists())

    def test_conflict_keeps_game_with_more_guesses(self):
        game_a = self.make_game(self.region, date(2024, 1, 1))
        game_b = self.make_game(self.region, date(2024, 1, 2))
        # game_a: anon has 2 guesses, account has 1 -> anon's wins
        anon_a = UserGame.objects.create(user=self.anon, game=game_a)
        Guess.objects.create(usergame=anon_a, bird=game_a.bird)
        Guess.objects.create(usergame=anon_a, bird=game_a.bird)
        acct_a = UserGame.objects.create(user=self.account, game=game_a)
        Guess.objects.create(usergame=acct_a, bird=game_a.bird)
        # game_b: tie -> account's wins
        anon_b = UserGame.objects.create(user=self.anon, game=game_b)
        Guess.objects.create(usergame=anon_b, bird=game_b.bird)
        acct_b = UserGame.objects.create(user=self.account, game=game_b)
        Guess.objects.create(usergame=acct_b, bird=game_b.bird)

        merge_anonymous_history(self.request_with_session(), self.account)

        self.assertEqual(UserGame.objects.filter(user=self.account).count(), 2)
        kept_a = UserGame.objects.get(user=self.account, game=game_a)
        self.assertEqual(kept_a.pk, anon_a.pk)
        self.assertEqual(kept_a.guess_count, 2)
        kept_b = UserGame.objects.get(user=self.account, game=game_b)
        self.assertEqual(kept_b.pk, acct_b.pk)
        self.assertFalse(UserGame.objects.filter(pk__in=[acct_a.pk, anon_b.pk]).exists())

    def test_non_anonymous_session_user_is_never_merged(self):
        other = User.objects.create_user("bob", "bob@example.com", "s3cret-pass")
        game = self.make_game(self.region, date(2024, 1, 1))
        UserGame.objects.create(user=other, game=game)
        self.session["username"] = other.username
        self.session.save()

        merge_anonymous_history(self.request_with_session(), self.account)

        self.assertTrue(User.objects.filter(pk=other.pk).exists())
        self.assertEqual(UserGame.objects.get(game=game).user, other)
        self.assertEqual(self.session["username"], self.account.username)

    def test_session_username_updated_on_login(self):
        game = self.make_game(self.region, date(2024, 1, 1))
        UserGame.objects.create(user=self.anon, game=game)

        response = self.client.post(
            "/accounts/login/", {"login": "alice@example.com", "password": "s3cret-pass"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session["username"], "alice")
        self.assertEqual(UserGame.objects.get(game=game).user, self.account)
        self.assertFalse(User.objects.filter(username=self.anon.username).exists())


@plain_static_storage
class ProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", "s3cret-pass")

    def test_anonymous_redirected_to_login(self):
        response = self.client.get("/accounts/profile/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/accounts/login/"))

    def test_username_change_persists_and_updates_session(self):
        self.client.force_login(self.user)
        response = self.client.post("/accounts/profile/", {"username": "alice2"})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "alice2")
        self.assertEqual(self.client.session["username"], "alice2")

    def test_all_digit_username_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post("/accounts/profile/", {"username": "12345"})
        self.assertContains(response, "cannot be all digits")
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "alice")

    def test_duplicate_username_rejected(self):
        User.objects.create_user("bob", "bob@example.com", "s3cret-pass")
        self.client.force_login(self.user)
        response = self.client.post("/accounts/profile/", {"username": "bob"})
        self.assertContains(response, "already exists")
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "alice")


@plain_static_storage
class AccountPagesSmokeTests(TestCase):
    def test_pages_render(self):
        for url in ["/accounts/login/", "/accounts/signup/", "/accounts/password/reset/"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
