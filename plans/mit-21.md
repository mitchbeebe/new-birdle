# MIT-21 — Add subscription (premium gating)

Branch: `mit-21-subscription`, based on `premium`. PR targets `premium`, not `main`.

## Summary

Add a paid "Birdle Premium" subscription via **Stripe Checkout + Billing Portal + webhooks**,
and a single `premium_required` gate that every other Premium tier issue will use. No custom
discount-code system: Stripe promotion codes handle the "free for me and friends" case, and an
admin-editable `comp_until` field covers one-off manual grants.

Why Stripe over Buy Me a Coffee / Patreon: only Stripe gives a webhook-driven entitlement the
app can enforce. BMAC/Patreon are donation links; we'd have no reliable way to know who paid.

## Data model (`birdle/models.py`)

```python
class Membership(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    stripe_customer_id = models.CharField(max_length=255, blank=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=32, blank=True)  # raw Stripe subscription status
    current_period_end = models.DateTimeField(null=True, blank=True)
    comp_until = models.DateTimeField(null=True, blank=True)  # manual grant, set in admin

    @property
    def is_active(self) -> bool:
        now = timezone.now()
        stripe_ok = self.status in {"active", "trialing"} and (
            self.current_period_end is None or self.current_period_end > now
        )
        comp_ok = self.comp_until is not None and self.comp_until > now
        return stripe_ok or comp_ok
```

Migration `0014_membership`. Register in `admin.py` with `list_display = ["user", "status",
"current_period_end", "comp_until"]`, `search_fields = ["user__username", "user__email"]`,
`raw_id_fields = ["user"]`.

## Gate (`birdle/premium.py`, new)

```python
def is_premium(user) -> bool  # False for anonymous; Membership.is_active otherwise

def premium_required(view):
    # login_required first (redirects to LOGIN_URL), then is_premium, else redirect("premium")
```

Also a template tag `{% is_premium as premium %}` in `views.py` (next to the existing
`register.simple_tag`s) so nav/profile can branch on it. Keep it a `takes_context` tag reading
`context["user"]`.

## Settings (`config/settings.py`)

```python
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_ENABLED = bool(STRIPE_SECRET_KEY and STRIPE_PRICE_ID)
```

Dependency: `stripe` (pin current 15.x via `uv add stripe`). `import stripe` inside the
views module and set `stripe.api_key` from settings at call time, not import time, so tests
and dev without keys still import cleanly.

## URLs (`config/urls.py`) — all before the `<str:region_code>/` catch-all

| path | name | view |
|---|---|---|
| `premium/` | `premium` | upgrade / status page |
| `premium/checkout/` | `premium_checkout` | POST only |
| `premium/success/` | `premium_success` | GET, after Checkout |
| `premium/portal/` | `premium_portal` | POST only |
| `premium/webhook/` | `stripe_webhook` | POST, csrf_exempt |

## Views (`birdle/views.py`)

- `premium(request)`: renders `birdle/premium.html`. Anonymous: pitch + "Log in to
  subscribe". Logged in and not premium: pitch + Subscribe button (POST to checkout), or
  "Subscriptions aren't available yet" when `not settings.STRIPE_ENABLED`. Premium: status
  (renewal date or comp expiry) + "Manage subscription" (POST to portal) when a
  `stripe_customer_id` exists.
- `premium_checkout` (`@login_required`, `@require_POST`): 503 if not enabled. Get-or-create
  `Membership`; if no `stripe_customer_id`, `stripe.Customer.create(email=..., metadata=
  {"user_id": ...})` and save it. Then `stripe.checkout.Session.create(mode="subscription",
  customer=..., line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
  allow_promotion_codes=True, client_reference_id=str(user.id),
  success_url=<abs premium_success>, cancel_url=<abs premium>)` and redirect (303) to
  `session.url`.
- `premium_success` (`@login_required`): render a "thanks, activating…" page that links back
  to `premium`. Do **not** grant premium here; the webhook is the source of truth. (Stripe can
  deliver the webhook before or after this redirect; the page just tells the user to refresh
  if it doesn't show yet.)
- `premium_portal` (`@login_required`, `@require_POST`): `stripe.billing_portal.Session.create(
  customer=..., return_url=<abs premium>)` → redirect.
- `stripe_webhook` (`@csrf_exempt`, `@require_POST`): verify with
  `stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)`; 400 on
  failure. Handle:
  - `checkout.session.completed`: look up user by `client_reference_id`; store
    `customer` and `subscription` ids on their Membership.
  - `customer.subscription.created` / `.updated` / `.deleted`: find Membership by
    `stripe_customer_id` (fall back to `stripe_subscription_id`); set `status` and
    `current_period_end` from the subscription object (`current_period_end` is a unix
    timestamp on the subscription in the API version stripe 15.x pins; if it's only on
    `items.data[0].current_period_end`, read it from there).
  - Anything else: 200 and ignore.
  Always return 200 once verified so Stripe stops retrying. Log unknown customers at warning
  level, don't raise.
- Put the Stripe calls behind small helpers in `birdle/premium.py` so tests can patch
  `birdle.premium.stripe`.

## Templates

- `birdle/templates/birdle/premium.html` and `premium_success.html`, extending
  `account/base_card.html` like `profile.html` does. Bullet the premium features (archive
  play, detailed stats, leaderboards, custom regions — link nothing yet).
- `base.html` nav: add a `Premium` link with `fa-star` between Info and the divider. Show
  `Premium ✓`-style badge text when `is_premium`.
- `profile.html`: one line showing membership status with a link to `premium`.

## Tests (`birdle/tests.py`)

- `PremiumGateTests`: anonymous → login redirect; logged-in non-premium → redirect to
  `/premium/`; comp'd user passes; active Stripe status passes; `past_due` fails; expired
  `current_period_end` fails; expired `comp_until` fails.
- `StripeWebhookTests`: patch `birdle.premium.stripe.Webhook.construct_event` to return
  dict-shaped events; assert `checkout.session.completed` stores ids and
  `customer.subscription.updated` sets status/period end; bad signature → 400; unknown
  customer → 200.
- `PremiumPagesTests`: `/premium/` renders for anonymous, non-premium, and premium users;
  checkout POST returns 503 when Stripe isn't configured.
- Use a tiny `settings` override (`@override_settings(STRIPE_ENABLED=False)` etc.) rather
  than real keys.

## External setup (user action required — copy into the PR body)

**Stripe dashboard** (test mode first, then repeat in live mode):
1. Products → Add product "Birdle Premium", recurring price (pick monthly; add yearly later
   if wanted). Copy the price id → `STRIPE_PRICE_ID`.
2. Developers → API keys: copy the secret key → `STRIPE_SECRET_KEY`.
3. Developers → Webhooks → Add endpoint `https://www.play-birdle.com/premium/webhook/`,
   events: `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`. Copy the signing secret
   → `STRIPE_WEBHOOK_SECRET`.
4. Settings → Billing → Customer portal: enable it, allow cancel + update payment method.
5. Products → Coupons: create a 100% off, duration "forever" coupon, then a Promotion code
   (e.g. `BIRDNERD`) on it for yourself and friends. Checkout has the promo code field
   enabled, so no app changes are needed to redeem it.
6. Local dev: `brew install stripe/stripe-cli/stripe`, `stripe login`, then
   `stripe listen --forward-to localhost:8001/premium/webhook/` and put the printed
   `whsec_…` in `.env` as `STRIPE_WEBHOOK_SECRET`. Test card `4242 4242 4242 4242`.
7. Production config vars: `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`.

## Verification
- `uv run ruff check`, `uv run ruff format --check`, `uv run ty check`, `python manage.py test`,
  `python manage.py makemigrations --check`.
- Manual (with test keys + `stripe listen`): subscribe with the test card → webhook fires →
  `/premium/` shows active; open portal → cancel → status flips at period end. Apply the promo
  code at Checkout → $0 subscription still activates. Set `comp_until` in admin → gate passes
  without Stripe.

## PR
- Push, `gh pr create --draft --base premium --head mit-21-subscription`, body links
  [MIT-21](https://linear.app/mitch-beebe/issue/MIT-21) and includes the external setup
  checklist. Set MIT-21 to In Review. Notify via `herdr notification show`.
