import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from allauth.socialaccount.adapter import get_adapter as get_socialaccount_adapter
from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth.models import AnonymousUser, User
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone as django_timezone

from .models import Bird, BirdRegion, Game, Guess, Membership, Region, UserGame
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

    def test_success_page_renders(self):
        self.client.force_login(self.user)
        response = self.client.get("/premium/success/")
        self.assertContains(response, "Go to Premium")
