"""Per-region leaderboards computed from UserGame/Guess with aggregate queries.

Each board function returns a list of (user_id, username, score) sorted by score
descending. Only accounts with an email set (real sign-ups) are ranked; the
auto-generated anonymous users are excluded from boards and from the total.
"""

from collections import defaultdict
from datetime import date, timedelta

from django.core.cache import cache
from django.db.models import Count, Exists, OuterRef

from .models import Guess, UserGame

CACHE_TIMEOUT = 60 * 10
TOP_N = 25


def _usergames(region_code):
    # TODO(MIT-5): filter is_archive=False once the archive field lands.
    return (
        UserGame.objects.filter(game__region__code=region_code)
        .exclude(user__email="")
        .annotate(
            num_guesses=Count("guess"),
            has_won=Exists(
                Guess.objects.filter(usergame=OuterRef("pk"), bird=OuterRef("game__bird"))
            ),
        )
    )


def _in_period(queryset, start, end):
    if start is not None:
        queryset = queryset.filter(game__date__gte=start)
    if end is not None:
        queryset = queryset.filter(game__date__lte=end)
    return queryset


def _sorted_rows(scores, usernames):
    rows = [(user_id, usernames[user_id], score) for user_id, score in scores.items() if score > 0]
    rows.sort(key=lambda row: (-row[2], row[1]))
    return rows


def _cached(key, compute):
    rows = cache.get(key)
    if rows is None:
        rows = compute()
        cache.set(key, rows, timeout=CACHE_TIMEOUT)
    return rows


def played(region_code, start, end):
    """Number of games with at least one guess in [start, end]."""

    def compute():
        games = (
            _in_period(_usergames(region_code), start, end)
            .filter(num_guesses__gt=0)
            .values_list("user_id", "user__username")
        )
        scores: dict[int, int] = defaultdict(int)
        usernames = {}
        for user_id, username in games:
            scores[user_id] += 1
            usernames[user_id] = username
        return _sorted_rows(scores, usernames)

    return _cached(f"leaderboard:played:{region_code}:{start}:{end}", compute)


def weighted_wins(region_code, start, end):
    """Sum over won games of 7 - num_guesses (1 guess = 6 pts, 6 guesses = 1 pt)."""

    def compute():
        wins = (
            _in_period(_usergames(region_code), start, end)
            .filter(has_won=True)
            .values_list("user_id", "user__username", "num_guesses")
        )
        scores: dict[int, int] = defaultdict(int)
        usernames = {}
        for user_id, username, num_guesses in wins:
            scores[user_id] += 7 - num_guesses
            usernames[user_id] = username
        return _sorted_rows(scores, usernames)

    return _cached(f"leaderboard:weighted_wins:{region_code}:{start}:{end}", compute)


def streaks(region_code, today):
    """Consecutive daily wins ending today or yesterday.

    Only users with a win in the last two days can have a live streak, so the
    candidate set is capped to them before their full win history is loaded.
    """

    def compute():
        wins = _usergames(region_code).filter(has_won=True)
        candidates = wins.filter(game__date__gte=today - timedelta(days=1)).values_list(
            "user_id", flat=True
        )
        won_dates: dict[int, set[date]] = defaultdict(set)
        usernames = {}
        for user_id, username, game_date in wins.filter(user_id__in=set(candidates)).values_list(
            "user_id", "user__username", "game__date"
        ):
            won_dates[user_id].add(game_date)
            usernames[user_id] = username
        scores = {}
        for user_id, dates in won_dates.items():
            day = today if today in dates else today - timedelta(days=1)
            streak = 0
            while day in dates:
                streak += 1
                day -= timedelta(days=1)
            scores[user_id] = streak
        return _sorted_rows(scores, usernames)

    return _cached(f"leaderboard:streaks:{region_code}:{today}", compute)


def rank_of(rows, user_id):
    """1-based position of user_id in rows, or None if unranked."""
    for index, (row_user_id, _, _) in enumerate(rows, start=1):
        if row_user_id == user_id:
            return index
    return None


def period_bounds(period, today):
    """(start, end) dates for a period name; 'all' has no bounds."""
    if period == "week":
        return today - timedelta(days=today.weekday()), today
    if period == "month":
        return today.replace(day=1), today
    return None, None
