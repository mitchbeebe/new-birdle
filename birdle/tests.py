import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from allauth.socialaccount.adapter import get_adapter as get_socialaccount_adapter
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone as django_timezone

from .models import (
    Bird,
    BirdRegion,
    CustomRegion,
    Game,
    Guess,
    Image,
    Membership,
    Region,
    UserGame,
)
from .ebird import EbirdError, fetch_nearby_species_codes
from .premium import premium_required
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


NAVBAR_MARKUP = '<a class="navbar-brand'

GOOGLE_TEST_PROVIDER = {
    "google": {"APPS": [{"client_id": "test-client-id", "secret": "test-secret", "key": ""}]}
}


@plain_static_storage
class AccountPagesSmokeTests(TestCase):
    def assert_styled(self, url, status_code=200):
        response = self.client.get(url)
        self.assertEqual(response.status_code, status_code)
        self.assertContains(response, NAVBAR_MARKUP, status_code=status_code)
        return response

    def test_account_pages_render_with_site_chrome(self):
        for url in [
            "/accounts/login/",
            "/accounts/signup/",
            "/accounts/password/reset/",
            "/accounts/login/code/",
        ]:
            with self.subTest(url=url):
                self.assert_styled(url)

    def test_socialaccount_error_pages_render_with_site_chrome(self):
        self.assert_styled("/accounts/3rdparty/login/cancelled/")
        # allauth serves the authentication error page with a 401
        self.assert_styled("/accounts/3rdparty/login/error/", status_code=401)

    @override_settings(SOCIALACCOUNT_PROVIDERS=GOOGLE_TEST_PROVIDER)
    def test_socialaccount_signup_renders_with_site_chrome(self):
        provider = get_socialaccount_adapter().get_provider(RequestFactory().get("/"), "google")
        sociallogin = SocialLogin(
            user=User(email="carol@example.com"),
            account=SocialAccount(provider="google", uid="123"),
            provider=provider,
        )
        session = self.client.session
        session["socialaccount_sociallogin"] = sociallogin.serialize()
        session.save()

        response = self.assert_styled("/accounts/3rdparty/signup/")
        self.assertContains(response, "Finish Signing Up")
        self.assertContains(response, 'class="form-control"')

    def test_fallback_layout_wraps_unoverridden_allauth_page(self):
        user = User.objects.create_user("alice", "alice@example.com", "s3cret-pass")
        self.client.force_login(user)
        response = self.assert_styled("/accounts/email/")
        self.assertContains(response, 'class="card-body"')


@premium_required
def gated_view(request):
    return HttpResponse("ok")


class PremiumGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", "s3cret-pass")
        self.factory = RequestFactory()

    def call(self, user):
        request = self.factory.get("/gated/")
        request.user = user
        return gated_view(request)

    def test_anonymous_redirected_to_login(self):
        response = self.call(AnonymousUser())
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/accounts/login/"))

    def test_non_premium_redirected_to_premium_page(self):
        response = self.call(self.user)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/premium/")

    def test_comp_user_passes(self):
        Membership.objects.create(
            user=self.user, comp_until=django_timezone.now() + timedelta(days=1)
        )
        self.assertEqual(self.call(self.user).status_code, 200)

    def test_active_stripe_status_passes(self):
        Membership.objects.create(
            user=self.user,
            status="active",
            current_period_end=django_timezone.now() + timedelta(days=30),
        )
        self.assertEqual(self.call(self.user).status_code, 200)

    def test_past_due_fails(self):
        Membership.objects.create(
            user=self.user,
            status="past_due",
            current_period_end=django_timezone.now() + timedelta(days=30),
        )
        self.assertEqual(self.call(self.user).status_code, 302)

    def test_expired_period_fails(self):
        Membership.objects.create(
            user=self.user,
            status="active",
            current_period_end=django_timezone.now() - timedelta(days=1),
        )
        self.assertEqual(self.call(self.user).status_code, 302)

    def test_expired_comp_fails(self):
        Membership.objects.create(
            user=self.user, comp_until=django_timezone.now() - timedelta(days=1)
        )
        self.assertEqual(self.call(self.user).status_code, 302)


class StripeWebhookTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", "s3cret-pass")

    def post_event(self, event):
        with patch("birdle.premium.stripe.Webhook.construct_event", return_value=event):
            return self.client.post(
                "/premium/webhook/",
                data=json.dumps(event),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="sig",
            )

    def test_checkout_completed_stores_ids(self):
        response = self.post_event(
            {
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_1",
                        "client_reference_id": str(self.user.pk),
                        "customer": "cus_1",
                        "subscription": "sub_1",
                    }
                },
            }
        )
        self.assertEqual(response.status_code, 200)
        membership = Membership.objects.get(user=self.user)
        self.assertEqual(membership.stripe_customer_id, "cus_1")
        self.assertEqual(membership.stripe_subscription_id, "sub_1")

    def test_subscription_updated_sets_status_and_period_end(self):
        Membership.objects.create(user=self.user, stripe_customer_id="cus_1")
        period_end = datetime(2030, 1, 1, tzinfo=timezone.utc)
        response = self.post_event(
            {
                "type": "customer.subscription.updated",
                "data": {
                    "object": {
                        "id": "sub_1",
                        "customer": "cus_1",
                        "status": "active",
                        "current_period_end": int(period_end.timestamp()),
                    }
                },
            }
        )
        self.assertEqual(response.status_code, 200)
        membership = Membership.objects.get(user=self.user)
        self.assertEqual(membership.status, "active")
        self.assertEqual(membership.stripe_subscription_id, "sub_1")
        self.assertEqual(membership.current_period_end, period_end)
        self.assertTrue(membership.is_active)

    def test_period_end_read_from_items_when_missing_on_subscription(self):
        Membership.objects.create(user=self.user, stripe_customer_id="cus_1")
        period_end = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.post_event(
            {
                "type": "customer.subscription.created",
                "data": {
                    "object": {
                        "id": "sub_1",
                        "customer": "cus_1",
                        "status": "trialing",
                        "items": {"data": [{"current_period_end": int(period_end.timestamp())}]},
                    }
                },
            }
        )
        membership = Membership.objects.get(user=self.user)
        self.assertEqual(membership.current_period_end, period_end)

    def test_bad_signature_returns_400(self):
        with patch("birdle.premium.stripe.Webhook.construct_event", side_effect=ValueError("bad")):
            response = self.client.post(
                "/premium/webhook/", data="{}", content_type="application/json"
            )
        self.assertEqual(response.status_code, 400)

    def test_unknown_customer_returns_200(self):
        response = self.post_event(
            {
                "type": "customer.subscription.deleted",
                "data": {"object": {"id": "sub_x", "customer": "cus_x", "status": "canceled"}},
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Membership.objects.exists())


@plain_static_storage
@override_settings(STRIPE_ENABLED=False)
class PremiumPagesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", "alice@example.com", "s3cret-pass")

    def test_anonymous_sees_login_prompt(self):
        response = self.client.get("/premium/")
        self.assertContains(response, "Log in to subscribe")

    def test_non_premium_sees_unavailable_when_stripe_disabled(self):
        self.client.force_login(self.user)
        response = self.client.get("/premium/")
        self.assertContains(response, "Subscriptions aren't available yet")

    @override_settings(STRIPE_ENABLED=True)
    def test_non_premium_sees_subscribe_button_when_enabled(self):
        self.client.force_login(self.user)
        response = self.client.get("/premium/")
        self.assertContains(response, "/premium/checkout/")

    def test_premium_user_sees_status(self):
        Membership.objects.create(
            user=self.user,
            status="active",
            stripe_customer_id="cus_1",
            current_period_end=django_timezone.now() + timedelta(days=30),
        )
        self.client.force_login(self.user)
        response = self.client.get("/premium/")
        self.assertContains(response, "Premium member")
        self.assertContains(response, "/premium/portal/")

    def test_checkout_returns_503_when_stripe_not_configured(self):
        self.client.force_login(self.user)
        response = self.client.post("/premium/checkout/")
        self.assertEqual(response.status_code, 503)

    @override_settings(STRIPE_ENABLED=True)
    def test_checkout_with_existing_subscription_syncs_and_redirects(self):
        Membership.objects.create(user=self.user, stripe_customer_id="cus_1")
        existing = {
            "id": "sub_1",
            "status": "active",
            "current_period_end": int(datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp()),
        }
        self.client.force_login(self.user)
        with patch("birdle.premium.find_subscription", return_value=existing) as find:
            with patch("birdle.premium.create_checkout_session") as create:
                response = self.client.post("/premium/checkout/")
        find.assert_called_once_with("cus_1")
        create.assert_not_called()
        self.assertRedirects(response, "/premium/", fetch_redirect_response=False)
        membership = Membership.objects.get(user=self.user)
        self.assertEqual(membership.status, "active")
        self.assertEqual(membership.stripe_subscription_id, "sub_1")

    def test_nav_shows_upsell_for_non_members_and_star_for_members(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get("/premium/"), "Go Premium")
        Membership.objects.create(
            user=self.user, comp_until=django_timezone.now() + timedelta(days=1)
        )
        response = self.client.get("/premium/")
        self.assertNotContains(response, "Go Premium")
        self.assertContains(response, "fa-star text-warning")

    def test_success_page_renders(self):
        self.client.force_login(self.user)
        response = self.client.get("/premium/success/")
        self.assertContains(response, "Go to Premium")


@plain_static_storage
class ArchiveTests(TestCase):
    def setUp(self):
        self.region, _ = Region.objects.get_or_create(code="world", defaults={"name": "World"})
        self.user = User.objects.create_user("alice", "alice@example.com", "s3cret-pass")
        # The views resolve "today" from the timezone cookie; pin it so the test date matches.
        self.client.cookies["timezone"] = "UTC"
        self.today = datetime.now(timezone.utc).date()
        self.games = {}
        for days_ago in (0, 1, 2):
            day = self.today - timedelta(days=days_ago)
            bird = make_bird(f"bird-{days_ago}")
            for i in range(2):
                Image.objects.create(
                    url=f"https://example.com/{bird.name}/{i}", label=str(i), bird=bird
                )
            self.games[days_ago] = Game.objects.create(date=day, bird=bird, region=self.region)
        self.yesterday_url = f"/world/archive/{self.games[1].date.isoformat()}/"

    def login(self, premium=True):
        if premium:
            Membership.objects.create(
                user=self.user, comp_until=django_timezone.now() + timedelta(days=1)
            )
        self.client.force_login(self.user)
        session = self.client.session
        session["username"] = self.user.username
        session.save()

    def test_non_premium_redirected_to_premium_page(self):
        self.login(premium=False)
        for url in ["/world/archive/", self.yesterday_url]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], "/premium/")

    def test_anonymous_redirected_to_login(self):
        for url in ["/world/archive/", self.yesterday_url]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith("/accounts/login/"))

    def calendar_cells(self, month):
        """Playable cells of the archive calendar for a month, keyed by date."""
        response = self.client.get(f"/world/archive/?month={month:%Y-%m}")
        self.assertEqual(response.status_code, 200)
        return {
            cell["date"]: cell
            for week in response.context["weeks"]
            for cell in week
            if cell and "date" in cell
        }

    def test_calendar_shows_past_games_only(self):
        self.login()
        cells = self.calendar_cells(self.today)
        self.assertNotIn(self.today, cells)
        for days_ago in (1, 2):
            game_date = self.games[days_ago].date
            with self.subTest(game_date=game_date):
                self.assertIn(game_date, self.calendar_cells(game_date))

    def test_calendar_hides_bird_name_until_finished(self):
        self.login()
        usergame = UserGame.objects.create(user=self.user, game=self.games[2], is_archive=True)
        Guess.objects.create(usergame=usergame, bird=self.games[2].bird)
        unplayed = self.calendar_cells(self.games[1].date)[self.games[1].date]
        self.assertIsNone(unplayed["bird"])
        self.assertEqual(unplayed["result"], "Not played")
        won = self.calendar_cells(self.games[2].date)[self.games[2].date]
        self.assertEqual(won["bird"], self.games[2].bird.name)
        self.assertEqual(won["result"], "Win")

    def test_calendar_month_navigation_is_bounded(self):
        self.login()
        response = self.client.get("/world/archive/")
        self.assertEqual(response.context["month"], self.today.replace(day=1))
        self.assertIsNone(response.context["next_month"])
        # Clamped to the current month when asked for the future; bad values fall back too.
        for month in ["2999-01", "garbage"]:
            with self.subTest(month=month):
                response = self.client.get(f"/world/archive/?month={month}")
                self.assertEqual(response.context["month"], self.today.replace(day=1))

    def test_play_past_game_creates_archive_usergame_and_records_guess(self):
        self.login()
        response = self.client.get(self.yesterday_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Back to archive")
        usergame = UserGame.objects.get(user=self.user, game=self.games[1])
        self.assertTrue(usergame.is_archive)

        response = self.client.post(
            self.yesterday_url,
            {"guess-input": self.games[1].bird.name, "game_id": self.games[1].pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_winner"])
        self.assertEqual(usergame.guess_count, 1)
        self.assertIn(str(self.games[1].date), response.json()["emojis"])

    def test_bad_dates_404(self):
        self.login()
        for day in [self.today.isoformat(), (self.today - timedelta(days=5)).isoformat(), "nope"]:
            with self.subTest(day=day):
                self.assertEqual(self.client.get(f"/world/archive/{day}/").status_code, 404)

    def test_existing_daily_usergame_is_reused(self):
        self.login()
        existing = UserGame.objects.create(user=self.user, game=self.games[1])
        self.client.get(self.yesterday_url)
        usergames = UserGame.objects.filter(user=self.user, game=self.games[1])
        self.assertEqual(usergames.count(), 1)
        self.assertEqual(usergames[0].pk, existing.pk)
        self.assertFalse(usergames[0].is_archive)

    def test_stats_ignore_archive_games(self):
        self.login()
        self.client.post(
            self.yesterday_url,
            {"guess-input": self.games[1].bird.name, "game_id": self.games[1].pk},
        )
        response = self.client.get("/world/stats/")
        self.assertEqual(response.context["games_won"], 0)
        self.assertEqual(response.context["games_played"], 0)


@plain_static_storage
@override_settings(EBIRD_API_KEY="test-key", EBIRD_ENABLED=True)
class CustomRegionTests(TestCase):
    FORM = {"lat": "40.71", "lng": "-74.01"}

    def setUp(self):
        Region.objects.get_or_create(code="world", defaults={"name": "World"})
        self.user = User.objects.create_user("alice", "alice@example.com", "s3cret-pass")
        self.birds = [make_bird(code) for code in ("amerob", "norcar", "blujay")]
        for bird in self.birds:
            for i in range(2):
                Image.objects.create(url=f"https://example.com/{bird.species_code}/{i}", bird=bird)
        cache.clear()

    def go_premium(self):
        Membership.objects.create(
            user=self.user, comp_until=django_timezone.now() + timedelta(days=1)
        )
        self.client.force_login(self.user)

    def build(self, codes, data=None):
        with patch("birdle.ebird.fetch_nearby_species_codes", return_value=codes) as fetch:
            response = self.client.post("/accounts/profile/custom-region/", data or self.FORM)
        return response, fetch

    def pool(self):
        custom = CustomRegion.objects.get(user=self.user)
        return set(
            BirdRegion.objects.filter(region=custom.region).values_list("bird_id", flat=True)
        )

    def test_pool_built_from_known_species_only(self):
        self.go_premium()
        response, fetch = self.build(["amerob", "blujay", "unknown-code"])
        self.assertRedirects(response, "/accounts/profile/")
        fetch.assert_called_once()
        custom = CustomRegion.objects.get(user=self.user)
        self.assertEqual(custom.region.code, f"custom-{self.user.pk}")
        self.assertEqual(custom.region.name, "Near me")
        self.assertEqual(custom.species_count, 2)
        self.assertIsNotNone(custom.built_at)
        self.assertEqual(self.pool(), {self.birds[0].id, self.birds[2].id})
        self.assertContains(self.client.get("/accounts/profile/"), "2 species")

    def test_empty_response_saves_empty_pool_with_warning(self):
        self.go_premium()
        self.build([])
        self.assertEqual(self.pool(), set())
        response = self.client.get("/accounts/profile/")
        self.assertContains(response, "0 species")
        self.assertContains(response, "small pool")
        # Nothing to play, so /custom/ sends them back to the profile.
        self.assertRedirects(self.client.get("/custom/"), "/accounts/profile/")

    def test_rebuild_replaces_pool(self):
        self.go_premium()
        self.build(["amerob"])
        self.assertEqual(self.pool(), {self.birds[0].id})
        with patch("birdle.ebird.fetch_nearby_species_codes", return_value=["norcar"]):
            self.client.post("/accounts/profile/custom-region/", self.FORM)
        self.assertEqual(self.pool(), {self.birds[1].id})
        self.assertEqual(CustomRegion.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Region.objects.filter(code__startswith="custom-").count(), 1)

    def test_ebird_error_renders_form_error(self):
        self.go_premium()
        with patch(
            "birdle.ebird.fetch_nearby_species_codes",
            side_effect=EbirdError("eBird returned HTTP 500."),
        ):
            response = self.client.post("/accounts/profile/custom-region/", self.FORM)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "eBird returned HTTP 500.")

    def test_invalid_coordinates_rejected(self):
        self.go_premium()
        response, fetch = self.build(["amerob"], {**self.FORM, "lat": "91"})
        self.assertContains(response, "Latitude must be")
        fetch.assert_not_called()
        self.assertFalse(CustomRegion.objects.exists())

    def test_anonymous_redirected_to_login(self):
        response = self.client.get("/custom/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/accounts/login/"))
        response = self.client.post("/accounts/profile/custom-region/", self.FORM)
        self.assertTrue(response["Location"].startswith("/accounts/login/"))

    def test_non_premium_redirected_to_premium(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get("/custom/"), "/premium/")
        self.assertRedirects(self.client.get("/custom/stats/"), "/premium/")
        response = self.client.post("/accounts/profile/custom-region/", self.FORM)
        self.assertRedirects(response, "/premium/")
        # The section is visible but disabled, pointing at the premium page.
        profile = self.client.get("/accounts/profile/")
        self.assertContains(profile, "Near me")
        self.assertContains(profile, "<fieldset disabled>")
        self.assertContains(profile, "This is a premium feature")

    def test_premium_without_region_redirected_to_profile(self):
        self.go_premium()
        self.assertRedirects(self.client.get("/custom/"), "/accounts/profile/")
        response = self.client.post(
            "/region",
            HTTP_HX_REQUEST="true",
            HTTP_HX_TRIGGER_NAME="custom",
            HTTP_HX_CURRENT_URL="http://testserver/world/",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Redirect"], "/accounts/profile/")

    def test_premium_user_can_play_and_see_stats(self):
        self.go_premium()
        self.build(["amerob"])
        response = self.client.get("/custom/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session["region_code"], "custom")
        game = Game.objects.get(region__code=f"custom-{self.user.pk}")
        self.assertEqual(game.bird, self.birds[0])
        self.assertEqual(
            response.context["emojis"],
            f"Near me Birdle\n{game.date}\n\nhttps://www.play-birdle.com/premium/",
        )

        # Autocomplete only offers the pool.
        suggestions = self.client.get("/api/birds/", {"guess-input": ""})
        self.assertContains(suggestions, "amerob")
        self.assertNotContains(suggestions, "norcar")

        response = self.client.post(
            "/custom/", {"guess-input": "amerob", "game_id": game.pk}, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_winner"])
        self.assertTrue(UserGame.objects.get(game=game).is_winner)

        response = self.client.get("/custom/stats/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["games_played"], 1)

    def test_fixed_regions_unaffected(self):
        self.assertEqual(self.client.get("/nope/").status_code, 404)
        self.assertEqual(self.client.get("/custom-1/").status_code, 404)
        # Free users see the premium entries disabled, linking to the premium page.
        page = self.client.get("/premium/")
        self.assertContains(page, "Near me <span")
        self.assertContains(page, "Archive <span")
        self.assertNotContains(page, "name=custom")
        self.go_premium()
        page = self.client.get("/premium/")
        self.assertContains(page, "name=custom")
        self.assertContains(page, "/archive/")

    def test_region_switcher_from_profile_goes_home(self):
        self.go_premium()
        self.build(["amerob"])
        response = self.client.post(
            "/region",
            HTTP_HX_REQUEST="true",
            HTTP_HX_TRIGGER_NAME="custom",
            HTTP_HX_CURRENT_URL="http://testserver/accounts/profile/",
        )
        self.assertEqual(response["HX-Redirect"], "/custom/")
        self.assertEqual(self.client.session["region_code"], "custom")
        response = self.client.post(
            "/region",
            HTTP_HX_REQUEST="true",
            HTTP_HX_TRIGGER_NAME="world",
            HTTP_HX_CURRENT_URL="http://testserver/custom/stats/",
        )
        self.assertEqual(response["HX-Redirect"], "/world/stats/")

    def test_htmx_post_returns_only_the_section(self):
        self.go_premium()
        with patch("birdle.ebird.fetch_nearby_species_codes", return_value=["amerob"]):
            response = self.client.post(
                "/accounts/profile/custom-region/", self.FORM, HTTP_HX_REQUEST="true"
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 species")
        self.assertContains(response, 'id="custom-region"')
        self.assertNotContains(response, NAVBAR_MARKUP)
        self.assertNotContains(response, "This is a premium feature")
        with patch("birdle.ebird.fetch_nearby_species_codes", side_effect=EbirdError("down")):
            response = self.client.post(
                "/accounts/profile/custom-region/", self.FORM, HTTP_HX_REQUEST="true"
            )
        self.assertContains(response, "down")
        self.assertNotContains(response, NAVBAR_MARKUP)
        response = self.client.post(
            "/accounts/profile/custom-region/delete/", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "1 species")
        self.assertFalse(CustomRegion.objects.exists())

    def test_delete_removes_region_and_resets_session(self):
        self.go_premium()
        self.build(["amerob"])
        self.client.get("/custom/")
        response = self.client.post("/accounts/profile/custom-region/delete/")
        self.assertRedirects(response, "/accounts/profile/")
        self.assertFalse(CustomRegion.objects.exists())
        self.assertFalse(Region.objects.filter(code__startswith="custom-").exists())
        self.assertEqual(self.client.session["region_code"], "world")


class FetchNearbySpeciesCodesTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(EBIRD_API_KEY="test-key", EBIRD_ENABLED=True)
    def test_fetch_parses_and_caches(self):
        payload = [{"speciesCode": "norcar"}, {"speciesCode": "amerob"}, {"speciesCode": "norcar"}]
        fake = type("R", (), {"status_code": 200, "json": lambda self: payload})()
        with patch("birdle.ebird.requests.get", return_value=fake) as get:
            first = fetch_nearby_species_codes("40.71", "-74.01")
            second = fetch_nearby_species_codes("40.71", "-74.01")
        self.assertEqual(first, ["amerob", "norcar"])
        self.assertEqual(second, first)
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs["headers"], {"X-eBirdApiToken": "test-key"})
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["dist"], 50)
        self.assertEqual(params["back"], 30)
        self.assertEqual(params["includeProvisional"], "false")

    @override_settings(EBIRD_API_KEY="test-key", EBIRD_ENABLED=True)
    def test_non_200_raises(self):
        fake = type("R", (), {"status_code": 403, "json": lambda self: []})()
        with patch("birdle.ebird.requests.get", return_value=fake):
            with self.assertRaises(EbirdError):
                fetch_nearby_species_codes("1", "2")

    @override_settings(EBIRD_API_KEY="", EBIRD_ENABLED=False)
    def test_unconfigured_raises(self):
        with self.assertRaises(EbirdError):
            fetch_nearby_species_codes("1", "2")
