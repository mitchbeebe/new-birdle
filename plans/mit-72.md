# MIT-72 — Detailed stats and accolades

Branch: `mit-72-accolades`, based on `premium`. PR targets `premium`. Same plan is committed at `plans/mit-72.md` on the branch.

## Summary

Add a premium-only "Accolades" section to the per-region stats page plus a few detailed-stats panels. Everything is computed from the user's existing `UserGame`/`Guess` rows, per region, with no new tables. Design: Apple-Fitness-style award tiles (icon, title, one-line stat, earned vs. locked), Bootstrap only.

**Prior art:** the stale branch `mit-72` (worktree `~/.herdr/worktrees/birdle/mit-72`) already implemented most of this against an older base: `get_taxonomy_stats`, best/worst/most-played order-family-genus, species identified, World Traveler, Catch 'Em All, and a `stats.html` section. Read `git diff $(git merge-base main mit-72) mit-72` and port the logic, but rewrite it to fit the current `stats()` view (annotated `num_guesses`/`has_won`, 10-minute per-user cache) rather than cherry-picking. Do not merge that branch.

## Scope (from the issue)

1. **Per-family accuracy** — table of family → games, wins, win %, sorted by games played, top 10.
2. **Hardest birds** — birds with most losses, then most guesses; top 5.
3. **Guess heatmap** — 7×N grid: weekday × hour-of-day (user tz) of guess timestamps, shaded by count. Render server-side as a table with CSS opacity classes; no chart library.
4. **Life list** — distinct species correctly identified across all regions, count + collapsible list grouped by family. This one is cross-region.
5. **Awards**: World Traveler (won every fixed region's game on one day — cross-region, exclude custom regions i.e. codes not in `get_regions()`), Catch 'Em All (identified every species in a family within the region; show best-progress family when unearned), Best/Worst family (min 3 games), Streak milestones (7, 30, 100).

## Code layout

New module `birdle/accolades.py` with pure functions taking querysets/lists and returning dicts; `stats()` calls one `detailed_stats(user, region_code, tz)` and adds the result to the context only when `is_premium(request.user)`. Keep the existing stats cache; include the premium block in the cached dict. Non-premium users see a teaser card with a link to `premium`.

Query budget: at most ~5 queries for the block. Use `values()` + `Count` for family accuracy; `select_related("bird")` on guesses for hardest birds/life list.

## Template

`stats.html`: new `{% if detailed %}` section after History, with award tiles in a responsive grid, then the tables/heatmap. Partial `birdle/_award.html` for a tile.

## Tests

`AccoladeTests`: family accuracy math; hardest-birds ordering; heatmap bucket counts respect tz; life list distinct across regions; World Traveler true only when every fixed region is won that day; Catch 'Em All earned/progress; non-premium user gets no `detailed` context; premium user does; cached stats invalidated after a guess (existing behavior).

## Verification

`ruff check`, `ruff format --check`, `ty check`, `python manage.py test`. No migration expected. Manual: seed a few games via admin, view `/world/stats/` as a premium (`comp_until`) user.

## Notes

* MIT-5 (archive, in review) adds `UserGame.is_archive`; once it merges, the accolade queries should exclude archive rows from streak-based awards but *include* them in life list. Leave a `# TODO(MIT-5)` at the filter site.
* Other branches add `0015_*` migrations; this one should not need a migration.
