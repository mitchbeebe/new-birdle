# MIT-5 — Play past games (archive)

Branch: `mit-5-archive`, based on `premium`. PR targets `premium`, not `main`.

## Summary

Logged-in premium users can browse a region's past daily games and play any they missed.
Archive plays are recorded with a flag so they never alter daily streaks or the stats
calendar. Games the user already played on the day are shown read-only in the archive.

**Gating note:** the `premium_required` decorator is being built in parallel on
`mit-21-subscription` (`birdle/premium.py`). Use `@login_required` here and mark each gated
view with `# TODO(MIT-21): swap for premium_required`. Do not try to import from the other
branch.

## Model change (`birdle/models.py`)

Add `is_archive = models.BooleanField(default=False)` to `UserGame`. Migration
`0014_usergame_is_archive`. (If `mit-21` lands first and also uses `0014`, renumber on rebase;
Django merges cleanly either way.)

## Refactor `daily_bird` so a game can be played by date (`birdle/views.py`)

Today `daily_bird` resolves `game = todays_game(...)`, resolves the user, then has a large
GET/POST body keyed on `game`. Split it:

```python
def daily_bird(request, region_code=None):
    ...region validation, session region, tz...
    game = todays_game(region_code, tz=user_tz)
    user = _session_user(request)              # existing get_or_create block, extracted
    usergame, _ = UserGame.objects.get_or_create(user=user, game=game)
    return _play(request, game, usergame, region_code)

@login_required  # TODO(MIT-21): swap for premium_required
def archive_game(request, region_code, date):
    ...same region validation...
    game = _past_game_or_404(region_code, date, user_tz)   # date < today in user tz
    user = _session_user(request)
    usergame, _ = UserGame.objects.get_or_create(
        user=user, game=game, defaults={"is_archive": True}
    )
    return _play(request, game, usergame, region_code, archive=True)
```

`_play` contains the existing GET (render) and POST (guess) logic unchanged, except:
- The POST `game_id` mismatch check stays; it works for archive pages too since the form posts
  back to the same URL.
- Pass `archive=True` and the game date into the template context so the page can show an
  "Archive · {date}" heading and the share text can say the date. Look at
  `build_results_emojis` — if the emoji header includes a day number or "today", make the
  archive variant use the game's date instead.
- Keep the `cache.delete(_stats_cache_key(...))` call; harmless.

Extract, don't rewrite: `_play` is the current body moved into a function. The diff for
`daily_bird` itself should be small.

## Archive list

`archive(request, region_code)` (`@login_required`, same TODO): all `Game`s for the region
with `date < today` (user tz), newest first, paginated with Django's `Paginator` at 30/page.
Annotate each row with the user's result: "Win", "Loss", "In progress", or "Not played",
using one query over `UserGame` for that user + those games (`select_related`/`annotate`
like `stats()` does — no per-row queries). Render `birdle/archive.html`: a simple table of
date, bird name (only when the user's game is finished — otherwise show "?" so the list
doesn't spoil the answer), result, and a Play/View link to `archive_game`.

## URLs (`config/urls.py`)

```python
path("<str:region_code>/archive/", views.archive, name="archive"),
path("<str:region_code>/archive/<str:date>/", views.archive_game, name="archive_game"),
```
Place them next to `stats_region`. `date` is `YYYY-MM-DD`; parse with
`datetime.date.fromisoformat`, 404 on `ValueError`, on no `Game` for that date/region, or on
`date >= today`.

## Stats (`birdle/views.py`, `stats()`)

Add `is_archive=False` to the `UserGame` filter so archive plays are excluded from games
played, wins, guess distribution, calendar, and streaks. That's the whole change there.

## Templates
- `birdle/templates/birdle/archive.html` (new), extends `birdle/base.html`, Bootstrap table
  + pagination links.
- `daily_bird.html`: when `archive` is set, show a small heading above the bird display:
  "Archive · {{ game_date }}" and a "Back to archive" link. Nothing else changes.
- `base.html` nav: add "Archive" (`fa-box-archive`) after Stats, href `/{{nav_region_code}}/archive/`.
  Show it only for authenticated users (the premium gate will tighten this later).

## Tests (`birdle/tests.py`)
- `ArchiveTests` (login as a real user via `self.client.force_login`, seed a Region, birds,
  and Games for yesterday, two days ago, and today):
  - anonymous → redirected to login for both views;
  - list shows past games only (today is absent), newest first;
  - list hides the bird name for unplayed games and shows it for finished ones;
  - playing a past game creates a `UserGame` with `is_archive=True`; posting a guess records it;
  - today's date and a date with no game → 404; malformed date → 404;
  - a game already played on the day (existing `is_archive=False` row) is reused, not
    duplicated, and keeps `is_archive=False`;
  - `stats()` ignores archive usergames (play an archive game to a win, assert
    `games_won` unchanged).
- Existing `daily_bird` behaviour must be untouched: run the full suite.

## Verification
- `uv run ruff check`, `uv run ruff format --check`, `uv run ty check`, `python manage.py test`,
  `python manage.py makemigrations --check`.
- Manual: log in, open `/world/archive/`, play yesterday's game, confirm the share text shows
  the right date and `/world/stats/` streak is unchanged.

## PR
- Push, `gh pr create --draft --base premium --head mit-5-archive`, body links
  [MIT-5](https://linear.app/mitch-beebe/issue/MIT-5) and notes the MIT-21 TODO. Set MIT-5 to
  In Review. Notify via `herdr notification show`.
