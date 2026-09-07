# MIT-14 — Leaderboards

Branch: `mit-14-leaderboards`, based on `premium`. PR targets `premium`. Same plan is committed at `plans/mit-14.md` on the branch.

## Summary

Per-region leaderboards for premium users, computed from `UserGame`/`Guess` with aggregate queries (no new tables). Three boards: games played, weighted wins, current streak. Each board shows the top 25 and the viewer's own rank ("You are #120 of 2,000").

Decisions (open questions in the issue, decided here to unblock):
* **Time period:** filter with `?period=all|month|week` (default `month`, calendar month/ISO week in the user's tz) for played and weighted-wins. Streak is always current streak, no period.
* **Display:** usernames, but only accounts that have an email set (real sign-ups). Anonymous auto-generated numeric-username users are excluded from boards and from the "of N players" denominator.
* **Region:** URL `/<region>/leaderboard/`, same validation as stats; region dropdown continues to work.
* **Friends-only filter:** blocked by MIT-12, out of scope. Leave a `?scope=friends` branch that calls a `friend_ids(user)` import guarded with a `# TODO(MIT-12)` — or simply omit it and note in the PR. Prefer omit.

## Scoring

* Played: count of `UserGame` with ≥1 guess in period.
* Weighted wins: sum over won games of `7 - num_guesses` (1 guess = 6 pts, 6 guesses = 1 pt).
* Streak: consecutive daily wins ending today or yesterday (in the user's tz). Compute in Python from each user's ordered won dates for the region; cap the candidate set to users with a win in the last 2 days to keep it cheap, since only they can have a live streak.

## Code

`birdle/leaderboards.py`: `played(region_code, start, end)`, `weighted_wins(...)`, `streaks(region_code, today)` each returning a list of `(user_id, username, score)` sorted desc, plus `rank_of(rows, user_id)`. Cache each board 10 minutes per (region, period). View `leaderboard(request, region_code)` `premium_required`; template `leaderboard.html` with three tabs (Bootstrap nav-tabs, no JS beyond Bootstrap) and a "Your rank" line under each. Nav link "Leaderboard" for premium users.

## Tests

`LeaderboardTests`: scoring for each board with a small fixture; period filtering; anonymous-username users excluded; viewer rank correct, and "unranked" when they have no games; anonymous → login, non-premium → `premium`; unknown region 404.

## Verification

`ruff check`, `ruff format --check`, `ty check`, `python manage.py test`. No migration expected.

## Notes

* MIT-5 (archive, in review) adds `UserGame.is_archive=True` for replayed past games. Once it merges, all three boards must filter `is_archive=False`. Add the filter behind a `# TODO(MIT-5)` comment now only if the field exists on your base; otherwise note it in the PR.
* MIT-182 adds per-user custom regions with codes `custom-<pk>`; leaderboards only apply to the fixed regions in `get_regions()`.
