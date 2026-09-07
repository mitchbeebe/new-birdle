"""Premium-only detailed stats and awards for the stats page.

Everything is derived from the user's existing ``UserGame``/``Guess`` rows. The
region-scoped panels work off the annotated ``usergames`` the stats view already
loaded; the cross-region panels (life list, World Traveler) run their own query.
"""

from collections import Counter, defaultdict

from django.db.models import Count, F

from .models import Bird, Guess

MIN_FAMILY_GAMES = 3
STREAK_MILESTONES = (7, 30, 100)
HEATMAP_LEVELS = 4
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def family_accuracy(usergames, limit=10):
    """Family -> games/wins/win %, sorted by games played."""
    played = Counter()
    won = Counter()
    for usergame in usergames:
        if usergame.num_guesses == 0:
            continue
        played[usergame.game.bird.family] += 1
        if usergame.has_won:
            won[usergame.game.bird.family] += 1
    rows = [
        {"family": family, "games": games, "wins": won[family], "win_pct": won[family] / games}
        for family, games in played.items()
    ]
    rows.sort(key=lambda row: (-row["games"], -row["win_pct"], row["family"]))
    return rows[:limit]


def hardest_birds(usergames, limit=5):
    """Birds with the most losses, then the most guesses spent on them."""
    by_bird = {}
    for usergame in usergames:
        if usergame.num_guesses == 0:
            continue
        bird = usergame.game.bird
        entry = by_bird.setdefault(bird.name, {"bird": bird.name, "losses": 0, "guesses": 0})
        entry["guesses"] += usergame.num_guesses
        if not usergame.has_won:
            entry["losses"] += 1
    rows = sorted(by_bird.values(), key=lambda r: (-r["losses"], -r["guesses"], r["bird"]))
    return rows[:limit]


def guess_heatmap(guessed_ats, tz):
    """7x24 grid of guess counts (weekday x hour in ``tz``) with a shade level per cell."""
    counts = Counter()
    for guessed_at in guessed_ats:
        local = guessed_at.astimezone(tz)
        counts[(local.weekday(), local.hour)] += 1
    peak = max(counts.values(), default=0)
    rows = []
    for weekday, label in enumerate(WEEKDAYS):
        cells = []
        for hour in range(24):
            count = counts[(weekday, hour)]
            level = 0 if count == 0 else max(1, round(count / peak * HEATMAP_LEVELS))
            cells.append({"hour": hour, "count": count, "level": level})
        rows.append({"day": label, "cells": cells})
    return {"rows": rows, "hours": list(range(24)), "total": sum(counts.values())}


def _winning_guesses(user):
    """One row per (species, date, region) the user has correctly identified, any region."""
    return (
        Guess.objects.filter(usergame__user=user, bird=F("usergame__game__bird"))
        .values_list(
            "bird__name",
            "bird__family",
            "usergame__game__date",
            "usergame__game__region__code",
        )
        .distinct()
    )


def life_list(wins):
    """Distinct species identified across all regions, grouped by family."""
    families = defaultdict(set)
    for name, family, _date, _region in wins:
        families[family].add(name)
    groups = [
        {"family": family, "species": sorted(species)}
        for family, species in sorted(families.items())
    ]
    return {"count": sum(len(g["species"]) for g in groups), "families": groups}


def world_traveler(wins, fixed_regions):
    """Earned when every fixed region's game was won on the same day (custom regions ignored)."""
    regions_by_date = defaultdict(set)
    for _name, _family, day, region in wins:
        if region in fixed_regions:
            regions_by_date[day].add(region)
    days = sorted(day for day, regions in regions_by_date.items() if regions >= fixed_regions)
    return {"earned": bool(days), "count": len(days), "latest": days[-1] if days else None}


def catch_em_all(usergames, region_code):
    """Identify every species in a family within the region; reports best progress when unearned."""
    totals = {
        row["family"]: row["total"]
        for row in Bird.objects.filter(birdregion__region__code=region_code)
        .values("family")
        .annotate(total=Count("id", distinct=True))
    }
    won = defaultdict(set)
    for usergame in usergames:
        if usergame.has_won:
            won[usergame.game.bird.family].add(usergame.game.bird_id)
    progress = [
        {"family": family, "won": len(species), "total": totals[family]}
        for family, species in won.items()
        if totals.get(family)
    ]
    progress.sort(key=lambda p: (-(p["won"] / p["total"]), -p["total"], p["family"]))
    earned = [p for p in progress if p["won"] == p["total"]]
    best = progress[0] if progress else None
    return {"earned": bool(earned), "families": earned, "best": best}


def awards(families, catch, traveler, best_streak):
    """Flatten award status into tiles: icon, title, one-line detail, earned flag."""
    tiles = []

    traveler_detail = (
        f"Earned {traveler['count']} time{'s' if traveler['count'] != 1 else ''}, "
        f"latest {traveler['latest']:%b} {traveler['latest'].day}, {traveler['latest'].year}"
        if traveler["earned"]
        else "Win every region's bird on the same day"
    )
    tiles.append(
        {
            "icon": "fa-earth-americas",
            "title": "World Traveler",
            "detail": traveler_detail,
            "earned": traveler["earned"],
        }
    )

    if catch["earned"]:
        names = ", ".join(f["family"] for f in catch["families"])
        catch_detail = f"Every species identified: {names}"
    elif catch["best"]:
        b = catch["best"]
        catch_detail = f"Closest: {b['family']} ({b['won']}/{b['total']})"
    else:
        catch_detail = "Identify every species in a family"
    tiles.append(
        {
            "icon": "fa-feather-pointed",
            "title": "Catch 'Em All",
            "detail": catch_detail,
            "earned": catch["earned"],
        }
    )

    eligible = [f for f in families if f["games"] >= MIN_FAMILY_GAMES]
    for title, icon, pick in (
        ("Best Family", "fa-trophy", max),
        ("Worst Family", "fa-face-frown", min),
    ):
        if eligible:
            fam = pick(eligible, key=lambda f: (f["win_pct"], f["games"]))
            detail = f"{fam['family']}: {fam['win_pct']:.0%} of {fam['games']} games"
        else:
            detail = f"Play a family {MIN_FAMILY_GAMES} times to unlock"
        tiles.append({"icon": icon, "title": title, "detail": detail, "earned": bool(eligible)})

    for milestone in STREAK_MILESTONES:
        earned = best_streak >= milestone
        detail = f"Best streak: {best_streak}" if earned else f"Win {milestone} days in a row"
        tiles.append(
            {
                "icon": "fa-fire",
                "title": f"{milestone}-Day Streak",
                "detail": detail,
                "earned": earned,
            }
        )
    return tiles


def detailed_stats(user, region_code, tz, usergames, best_streak, fixed_regions):
    """Build the premium block of the stats context. Three queries beyond ``usergames``."""
    # TODO(MIT-5): once UserGame.is_archive lands, exclude archive rows from the
    # streak-based awards here but keep them in the life list.
    usergames = list(usergames)
    guessed_ats = Guess.objects.filter(
        usergame__user=user, usergame__game__region__code=region_code
    ).values_list("guessed_at", flat=True)
    wins = list(_winning_guesses(user))

    families = family_accuracy(usergames)
    catch = catch_em_all(usergames, region_code)
    traveler = world_traveler(wins, set(fixed_regions))
    return {
        "awards": awards(families, catch, traveler, best_streak),
        "families": families,
        "hardest": hardest_birds(usergames),
        "heatmap": guess_heatmap(guessed_ats, tz),
        "life_list": life_list(wins),
    }
