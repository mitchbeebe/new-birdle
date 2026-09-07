# User accounts — MIT-8 (Login/Sign-up) + MIT-9 (Profile/settings)

Branch: `user-accts` (off `origin/main`). One draft PR covers both issues.

## Summary

Add real accounts on top of the existing anonymous play model using `django-allauth`
(pin the current 65.x release). Three ways in: Google OAuth, email + password, and
passwordless email login (allauth "login by code" — a one-time code emailed to the user; this
is the supported allauth equivalent of a magic link). Password reset via email. Email is sent
through Resend's SMTP endpoint using Django's built-in SMTP backend — no Resend SDK.

Anonymous play keeps working exactly as today. When an anonymous player logs in or signs up,
their session's game history is merged into the account.

A `/accounts/profile/` page lets a logged-in user change their username and change their
password (or set one, for Google/code-only accounts).

## How anonymous users work today (do not break this)

- `birdle/views.py:92-99` (`daily_bird`): the session key `username` holds a numeric
  timestamp string. `User.objects.get_or_create(username=...)` creates a passwordless
  `auth.User` row per anonymous visitor. `stats()` (`views.py:197-201`) reads the same session
  key. There is no `request.user` usage anywhere.
- `UserGame(user, game)` has no unique constraint, but the views only ever `get_or_create`
  one per (user, game).

## Design decisions

1. **Keep session `username` as the single source of truth for gameplay.** Views stay
   untouched except where noted. After login, set `request.session["username"] =
   request.user.username`. After username change, do the same. On logout, allauth flushes the
   session, so the next request creates a fresh anonymous user — that's the desired behavior.
   This avoids touching `daily_bird`/`stats` logic.
2. **Merge, don't link.** Anonymous `UserGame` rows are re-pointed to the real user; the
   anonymous `User` row is then deleted. Anonymous users are recognizable by
   `not user.has_usable_password() and user.email == "" and username.isdigit()`; never merge a
   user that fails that test.
3. **Conflict rule** when both the anonymous user and the account already have a `UserGame`
   for the same `Game`: keep the one with more guesses (ties → keep the account's), delete the
   other. Guesses cascade.
4. **No `django.contrib.sites` dependency for Google.** Configure the provider app in settings
   from env vars (`SOCIALACCOUNT_PROVIDERS["google"]["APPS"]`) so nothing has to be seeded in
   the DB. Hide the Google button when `GOOGLE_OAUTH_CLIENT_ID` is unset.
5. **Email verification: `optional`.** Login-by-code and password reset work without it, and
   mandatory verification would block Google-less signups from playing. Revisit later.
6. **Username on signup:** required for email/password signup. Google signups get allauth's
   auto-generated username (from the email local part) and can change it on the profile page.

## Files

### Dependencies
- `pyproject.toml`: add `django-allauth[socialaccount]==65.x.y` (whatever `uv add` resolves;
  pin exact). Run `uv lock`. Note: allauth 65 requires `asgiref>=3.8.1`; the project pins
  `asgiref==3.7.2`, so bump that pin to whatever resolves (Django 5.0.1 is fine with it).

### `config/settings.py`
- `INSTALLED_APPS`: add `allauth`, `allauth.account`, `allauth.socialaccount`,
  `allauth.socialaccount.providers.google`.
- `MIDDLEWARE`: append `allauth.account.middleware.AccountMiddleware`.
- `AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend",
  "allauth.account.auth_backends.AuthenticationBackend"]`.
- allauth settings:
  ```python
  ACCOUNT_LOGIN_METHODS = {"email"}
  ACCOUNT_SIGNUP_FIELDS = ["email*", "username*", "password1*", "password2*"]
  ACCOUNT_EMAIL_VERIFICATION = "optional"
  ACCOUNT_LOGIN_BY_CODE_ENABLED = True
  ACCOUNT_LOGOUT_ON_GET = False
  ACCOUNT_SESSION_REMEMBER = True
  LOGIN_REDIRECT_URL = "/"
  ACCOUNT_LOGOUT_REDIRECT_URL = "/"
  SOCIALACCOUNT_LOGIN_ON_GET = True
  SOCIALACCOUNT_PROVIDERS = {
      "google": {
          "APPS": [{"client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID", ""),
                    "secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""), "key": ""}],
          "SCOPE": ["profile", "email"],
          "AUTH_PARAMS": {"access_type": "online"},
      }
  }
  ```
  Only include the `APPS` entry when the client id is set (otherwise allauth errors on an
  empty app).
- Email:
  ```python
  DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "Birdle <noreply@play-birdle.com>")
  if os.getenv("RESEND_API_KEY"):
      EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
      EMAIL_HOST = "smtp.resend.com"
      EMAIL_PORT = 587
      EMAIL_USE_TLS = True
      EMAIL_HOST_USER = "resend"
      EMAIL_HOST_PASSWORD = os.environ["RESEND_API_KEY"]
  else:
      EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
  ```
- `CSRF_TRUSTED_ORIGINS`: leave as is.

### `config/urls.py`
- Add `path("accounts/profile/", views.profile, name="profile")` **before**
  `path("accounts/", include("allauth.urls"))`, and both before the `<str:region_code>/`
  catch-all so `accounts` is never treated as a region.

### `birdle/signals.py` (new) + `birdle/apps.py`
- Receiver on `allauth.account.signals.user_logged_in` (fires for password, code, and social
  logins, and after signup). Implement `merge_anonymous_history(request, user)`:
  1. `anon_username = request.session.get("username")`; bail if missing, equal to
     `user.username`, or the row doesn't exist or isn't anonymous per decision 2.
  2. For each `UserGame` of the anon user: if the account has none for that game, re-point
     `user`; else apply the conflict rule (decision 3).
  3. Delete the anonymous `User`.
  4. `request.session["username"] = user.username`.
  Wrap in `transaction.atomic()`.
- Import `birdle.signals` in `BirdleConfig.ready()`.

### `birdle/forms.py`
- `UsernameForm(forms.ModelForm)` on `User`, field `username`, Bootstrap `form-control`
  widget. Reject usernames that are all digits (they'd collide with the anonymous scheme).

### `birdle/views.py`
- `profile(request)`: `@login_required`. GET renders the form with current username, the
  user's email, and links to `account_change_password` (or `account_set_password` when
  `not request.user.has_usable_password()`) and `account_reset_password`. POST validates,
  saves, updates `request.session["username"]`, re-renders with a success message.
- No other view changes. (Do not switch `daily_bird`/`stats` to `request.user`.)

### Templates
- `birdle/templates/birdle/base.html`: in the offcanvas nav, add a divider then either
  `Log in` (→ `account_login`) or `<username>` (→ `profile`) + `Log out` (POST form to
  `account_logout` — `ACCOUNT_LOGOUT_ON_GET` is off).
- `birdle/templates/account/` overrides, each extending `birdle/base.html` and rendering
  allauth's forms with Bootstrap classes: `login.html` (email/password form, "Email me a
  login code" link to `account_request_login_code`, Google button via
  `{% provider_login_url 'google' %}` guarded by `{% if socialaccount_providers %}` or the
  settings flag), `signup.html`, `logout.html`, `password_reset.html`,
  `password_reset_done.html`, `password_reset_from_key.html`,
  `password_reset_from_key_done.html`, `password_change.html`, `password_set.html`,
  `request_login_code.html`, `confirm_login_code.html`, `email_confirm.html`.
  Keep them minimal — one card per page, matching the existing Bootstrap 5.3 look. Do **not**
  override allauth's email templates; the defaults are fine.
- `birdle/templates/birdle/profile.html` (new).
- The closed PR #45 (branch `origin/mit-8`) has a prior pass at several of these templates.
  You may crib markup from it, but do not merge or cherry-pick that branch — it was based on
  an older main and used a different merge approach.

### `birdle/tests.py`
- `AnonymousMergeTests`: (a) history moves to the account and the anon user is deleted;
  (b) conflict keeps the game with more guesses; (c) a non-anonymous session user is never
  merged; (d) session `username` is updated.
- `ProfileTests`: anonymous → redirected to login; username change persists and updates the
  session; all-digit username rejected; duplicate username rejected.
- Smoke: `/accounts/login/`, `/accounts/signup/`, `/accounts/password/reset/` return 200.
- Tests need a `World` region + at least one bird/game; use helpers like `make_bird` already
  in `tests.py`.

### Migrations
- allauth ships its own; run `python manage.py makemigrations --check` to confirm none are
  needed for `birdle` (no model changes planned).

## External setup (user action required — flag these in the PR body)

**Google Cloud Console** (credentials already exist in `.env`):
1. APIs & Services → OAuth consent screen: set app name "Birdle", support email, and
   publish (or add test users while in Testing).
2. Credentials → the OAuth client: add Authorized redirect URIs
   `http://localhost:8001/accounts/google/login/callback/` and
   `https://www.play-birdle.com/accounts/google/login/callback/` (plus the apex domain if it
   serves the app). Authorized JavaScript origins: `http://localhost:8001`,
   `https://www.play-birdle.com`.

**Resend**:
3. Domains → Add domain `play-birdle.com` (region of your choice). Resend shows DKIM,
   SPF/MX (for the `send` subdomain), and optional DMARC records.
4. API Keys → create a key with "Sending access" scoped to that domain. Put it in local `.env`
   as `RESEND_API_KEY` and in production config as `RESEND_API_KEY`.

**Cloudflare DNS** (`play-birdle.com` zone):
5. Add the records Resend gave you: `TXT resend._domainkey` (DKIM), `MX send` →
   `feedback-smtp.<region>.amazonses.com` priority 10, `TXT send` → `v=spf1 include:amazonses.com ~all`,
   and `TXT _dmarc` → `v=DMARC1; p=none;`. Set them to **DNS only** (grey cloud), not proxied.
6. Back in Resend, click Verify. Delivery from `noreply@play-birdle.com` fails until this is
   green; the console email backend is used locally so dev is unaffected.

**Production config vars** (Heroku today; Fly once the DevOps milestone lands):
7. `RESEND_API_KEY`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, and optionally
   `DEFAULT_FROM_EMAIL`.

## Verification
- `uv run ruff check`, `uv run ruff format --check`, `uv run ty check`,
  `python manage.py test` all pass.
- Manual on `runserver 8001`: play a game anonymously → sign up with email → stats page still
  shows today's game; log out → new anonymous user; log in again → history restored.
- Manual: request a login code; the code prints to the console backend; entering it logs in.
- Manual: change username on `/accounts/profile/`; nav and stats reflect it.
- Google end-to-end only works after the external steps above; note that in the PR.

## PR
- `git push -u origin user-accts`, then `gh pr create --draft --base main --head user-accts`
  with a body that links MIT-8 and MIT-9, summarizes the approach, lists the manual checks,
  and copies the "External setup" checklist verbatim so the user can tick it off.
- Set MIT-8 and MIT-9 to "In Review" in Linear when the PR is open.
