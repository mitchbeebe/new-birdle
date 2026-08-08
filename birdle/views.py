import json
import random
import re
import requests
import requests.adapters
from bs4 import BeautifulSoup
from django.shortcuts import redirect, render
from urllib.parse import quote, unquote, urlparse
from django.contrib.auth.models import User
from .models import Bird, Guess, Game, UserGame, Image, BirdRegion, Region
from .forms import BirdRegionForm
from django.core.cache import cache
from django.db.models import Count, Exists, OuterRef, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.template.defaulttags import register
import pytz
from datetime import datetime, timezone
from random import choices
from pandas import date_range


def random_bird(region_code="world"):
    # Randomly draw a bird from the region provided
    region = Region.objects.get(code=region_code)
    birdregions = BirdRegion.objects.filter(region=region)
    count = birdregions.count()
    idx = random.randrange(0, count)
    bird = birdregions[idx].bird
    return bird


def get_user_timezone(request):
    """Get the user's timezone from their browser cookie, defaulting to Eastern."""
    tz_name = request.COOKIES.get("timezone", "US/Eastern")
    try:
        return pytz.timezone(tz_name)
    except pytz.exceptions.UnknownTimeZoneError:
        return pytz.timezone("US/Eastern")


def todays_game(region_code="world", tz=None):
    # Get current date in user's timezone (or Eastern if not provided)
    if tz is None:
        tz = pytz.timezone("US/Eastern")
    today = datetime.now(timezone.utc).astimezone(tz).strftime("%Y-%m-%d")
    region = Region.objects.get(code=region_code)
    try:
        # Assumes an already created game is valid
        game = Game.objects.get(date=today, region=region)
    except Game.DoesNotExist:
        # Randomly select a bird
        bird = random_bird(region_code)
        imgs = get_bird_images(bird)

        # Create game if at least two images
        if len(imgs) >= 2:
            game, _ = Game.objects.update_or_create(
                date=today, region=region, defaults={"bird": bird}
            )
        else:
            # Redraw bird if fewer than 2 images
            return todays_game(region_code, tz)
    return game


def _stats_cache_key(username, region_code):
    return f"stats:{username}:{region_code}"


def daily_bird(request, region_code=None):
    # Redirect to regional URL if no region code provided
    if not region_code:
        region_code = request.session.get("region_code", "world")
        return redirect("daily_bird_region", region_code=region_code)

    # Validate region code
    if region_code not in get_regions():
        raise Http404("Region not found")
    request.session["region_code"] = region_code

    user_tz = get_user_timezone(request)
    game = todays_game(region_code, tz=user_tz)

    # Get user if available
    old_username = request.POST.get("user_id")
    if old_username:
        username = old_username
    else:
        username = request.session.get("username", int(datetime.now().timestamp() * 100))
    user, _ = User.objects.get_or_create(username=username)
    request.session["username"] = user.username

    usergame, _ = UserGame.objects.get_or_create(user=user, game=game)

    if request.method == "GET":
        imgs = get_bird_images(bird=game.bird, game=game)
        # Get past guesses
        guesses = Guess.objects.filter(usergame=usergame).order_by("guessed_at")
        # Convert guesses to Birds
        bird_guesses = [guess.bird for guess in guesses]

        # Calculate correct taxonomy for autocomplete filtering
        correct_taxonomy = {"order": None, "family": None, "genus": None}
        for bird_guess in bird_guesses:
            correctness = bird_guess.compare(game.bird)
            if correctness[0]:
                correct_taxonomy["order"] = bird_guess.order
            if correctness[1]:
                correct_taxonomy["family"] = bird_guess.family
            if correctness[2]:
                correct_taxonomy["genus"] = bird_guess.genus

        context = {
            "game_id": game.id,
            "imgs": imgs,
            "bird": game.bird,
            "is_winner": usergame.is_winner,
            "correct_taxonomy": correct_taxonomy,
            "guesses": [{**b.info(), "correctness": b.compare(game.bird)} for b in bird_guesses],
            "guess_count": usergame.guess_count,
            "emojis": build_results_emojis(game, guesses),
            "hint": get_hint_data(usergame.guess_count, game.bird, usergame.is_winner),
        }
        return render(request, "birdle/daily_bird.html", context)

    elif request.method == "POST":
        # Validate the game hasn't changed (new day started)
        submitted_game_id = request.POST.get("game_id")
        if submitted_game_id and int(submitted_game_id) != game.id:
            response = HttpResponse(status=409)  # Conflict
            response["HX-Trigger"] = json.dumps({"gameExpired": {}})
            return response

        # Get the Bird the user guessed
        try:
            guess = Bird.objects.get(name=request.POST.get("guess-input"))
        except KeyError, Bird.DoesNotExist:
            response = HttpResponse(status=400)
            response["HX-Trigger"] = json.dumps({"guessFailed": {}})
            return response

        # Check if they still have guesses and have not won already
        if usergame.guess_count < 6 and not usergame.is_winner:
            # Add the user's guess to the database
            Guess.objects.create(
                usergame=usergame,
                bird=guess,
                hint_used=request.POST.get("hint_used") == "true",
            )
            # Invalidate every region's cached stats for this user, not just the
            # current one: world_traveler is cross-region (see MIT-6), so a win in
            # one region can change the cached stats of every other region too.
            for other_region_code in get_regions():
                cache.delete(_stats_cache_key(user.username, other_region_code))

        # Get all user guesses
        guesses = Guess.objects.filter(usergame=usergame).order_by("guessed_at")

        # Convert guesses to Birds
        bird_guesses = [guess.bird for guess in guesses]

        correctness = guess.compare(game.bird)
        guess_count = guesses.count()

        context = {
            "is_winner": usergame.is_winner,
            "new_guess": render_to_string(
                "birdle/guess.html",
                {**guess.info(), "correctness": correctness},
            ),
            "guess_count": guess_count,
            "emojis": build_results_emojis(game, guesses),
            "taxonomy": {
                "order": guess.order if correctness[0] else None,
                "family": guess.family if correctness[1] else None,
                "genus": guess.genus if correctness[2] else None,
            },
            "hint": get_hint_data(guess_count, game.bird, usergame.is_winner),
        }
        return JsonResponse(context)


def stats(request, region_code=None):
    # Redirect to regional URL if no region code provided
    if not region_code:
        region_code = request.session.get("region_code", "world")
        return redirect("stats_region", region_code=region_code)

    # Validate region code
    if region_code not in get_regions():
        raise Http404("Region not found")
    request.session["region_code"] = region_code

    username = request.session.get("username")
    user_tz = get_user_timezone(request)
    cache_key = _stats_cache_key(username, region_code) if username else None
    stats = cache.get(cache_key) if cache_key else None
    # Retrieve the user's guess history from the database
    if username and stats is None:
        usergames = (
            UserGame.objects.filter(user__username=username, game__region__code=region_code)
            .select_related("game__bird")
            .annotate(
                num_guesses=Count("guess"),
                has_won=Exists(
                    Guess.objects.filter(usergame=OuterRef("pk"), bird=OuterRef("game__bird"))
                ),
            )
        )
        today = datetime.now(timezone.utc).astimezone(user_tz).date()
        first_game = min([usergame.game.date for usergame in usergames] + [today])
        games = Game.objects.filter(
            date__gte=first_game, date__lte=today, region__code=region_code
        ).order_by("date")

        # User stats
        games_played = len([game for game in usergames if game.num_guesses > 0])
        wins = [game for game in usergames if game.has_won]
        games_won = len(wins)
        win_pct = games_won / games_played if games_played > 0 else 0
        guess_counts = [game.num_guesses for game in wins if game.num_guesses > 0]
        guess_dist = [{"guesses": i, "count": guess_counts.count(i)} for i in range(1, 7)]

        def result(game):
            if game.num_guesses == 0:
                result = "Did not play"
            elif game.has_won:
                result = "Win"
            else:
                result = "Loss"
            return result

        game_results = {str(usergame.game.date): result(usergame) for usergame in usergames}

        # Create daily data for calendar view
        date_list = date_range(first_game, today, freq="D").map(lambda x: x.strftime("%Y-%m-%d"))
        results = [game_results.get(date, "Did not play") for date in date_list]

        # Create date-to-bird mapping to handle missing Game objects
        game_birds = {str(game.date): game.bird.name for game in games}

        history = [
            {"Date": date, "Result": result, "Bird": game_birds.get(date, "No game")}
            for date, result in zip(date_list, results)
        ]

        # Hide todays result if they're still playing and haven't won
        todays_result = usergames.filter(game__date=today)
        if todays_result:
            history = (
                history[0:-1]
                if todays_result[0].num_guesses < 6 and not todays_result[0].has_won
                else history
            )
        else:
            history = history[0:-1]

        # Calculate streak
        streaks = []
        streak = 0
        for result in results:
            if result == "Win":
                streak += 1
            else:
                streak = 0
            streaks.append(streak)

        current_streak = streaks[-1]
        best_streak = max(streaks)

        taxonomy_stats = get_taxonomy_stats(usergames)
        most_played = get_most_played_accolades(taxonomy_stats)
        best = get_best_accolades(taxonomy_stats)
        worst = get_worst_accolades(taxonomy_stats)
        species_identified = get_species_identified(taxonomy_stats)
        world_traveler = get_world_traveler_status(username)
        catch_em_all = get_catch_em_all_progress(taxonomy_stats, region_code)

        stats = {
            "games_played": games_played,
            "games_won": games_won,
            "win_pct": f"{win_pct:.0%}",
            "guess_freq": json.dumps(guess_dist),
            "history": json.dumps(history),
            "current_streak": current_streak,
            "best_streak": best_streak,
            "most_played": most_played,
            "best": best,
            "worst": worst,
            "species_identified": species_identified,
            "world_traveler": world_traveler,
            "catch_em_all": catch_em_all,
        }
        cache.set(cache_key, stats, timeout=60 * 10)
    elif not username:
        stats = {
            "games_played": 0,
            "games_won": 0,
            "win_pct": "N/A",
            "guess_freq": json.dumps([]),
            "history": json.dumps([]),
            "current_streak": 0,
            "best_streak": 0,
            "most_played": {},
            "best": {},
            "worst": {},
            "species_identified": {},
            "world_traveler": {"earned": False, "count": 0, "latest": None},
            "catch_em_all": {"family": [], "genus": []},
        }
    # Render the guess history template with the data
    return render(request, "birdle/stats.html", stats)


def info(request):
    return render(request, "birdle/info.html")


def practice(request, **kwargs):
    if request.method == "GET":
        data = {}
        if kwargs.values():
            region = kwargs.get("region")
            family = kwargs.get("family")
            decoded_region = unquote(region) if region else "Any"
            decoded_family = unquote(family) if family else "Any"

            birdregions = BirdRegion.objects.all()
            if decoded_region == "Any" and decoded_family == "Any":
                birds = Bird.objects.all()
            else:
                if decoded_region != "Any":
                    birdregions = birdregions.filter(region__name=decoded_region)
                if decoded_family != "Any":
                    birdregions = birdregions.filter(bird__family=decoded_family)
                birds = [x.bird for x in birdregions]

            birds_choices = choices(birds, k=4)
            bird = choices(birds_choices, k=1)[0]
            imgs = get_bird_images(bird=bird)
            options = list(set([bird.name for bird in birds_choices]))
            data.update({"imgs": imgs, "options": options, "answer": bird})
            form = BirdRegionForm(initial={"region": decoded_region, "family": decoded_family})
        else:
            form = BirdRegionForm()
        return render(request, "birdle/practice.html", {"form": form, **data})
    elif request.method == "POST":
        form = BirdRegionForm(request.POST)
        if form.is_valid():
            region = quote(form.cleaned_data["region"])
            family = quote(form.cleaned_data["family"])
            return redirect("practice-region-family", region=region, family=family)
        else:
            return render(request, "birdle/practice.html", {"form": form})


def get_bird_images(bird, game=None):
    images = Image.objects.filter(bird=bird).order_by("id")

    if images.count() > 1:
        return images
    else:
        # Open session to try three requests three times
        ebird_sesh = requests.Session()
        ebird_adapter = requests.adapters.HTTPAdapter(max_retries=3)
        ebird_sesh.mount("https://", ebird_adapter)

        # Get and parse the bird page on eBird
        response = ebird_sesh.get(bird.url)
        soup = BeautifulSoup(response.content, "html.parser")

        # Get divs that contain images and captions
        items = soup.find_all("div", class_="CarouselResponsive-slide--photo")

        # Get labels and photographer from the image alt text
        alt_labels = [x.find("img", class_="Species-media-image")["alt"] for x in items]
        raw_labels = [label.split(" - ")[0] for label in alt_labels]
        labels = [label or "Version " + str(i + 1) for i, label in enumerate(raw_labels)]
        photographer = [p.split(" - ")[1] for p in alt_labels]

        # Get the image url
        url_srcs = [x.find("img")["srcset"] for x in items]
        pattern = r"https:\/\/cdn.download\.ams.birds\.cornell\.edu\/api\/v1\/asset\/\d+\/1800"
        urls = [match.group() for src in url_srcs if (match := re.search(pattern, src))]

        # Zip everything together
        img_list = list(zip(labels, urls, photographer))

        # Get the range, if it exists
        range_req = requests.get(
            f"https://birdsoftheworld.org/bow/species/{bird.species_code}/cur/introduction"
        )
        range_soup = BeautifulSoup(range_req.content, "html.parser")
        try:
            range_url = range_soup.find_all("figure", class_="Figure")[0].find("a")[
                "data-asset-src"
            ]
        except IndexError:
            HttpResponse("Range not found", status=400)
        else:
            img_list.append(("Range", range_url, None))

        imgs = []
        for label, url, photographer in img_list:
            img, _ = Image.objects.update_or_create(
                url=url, label=label, photographer=photographer, bird=bird
            )
            imgs.append(img)

        return imgs


def bird_autocomplete(request):
    # Only show birds in region
    region_code = request.session.get("region_code", "world")

    query = request.GET.get("guess-input", "") or request.GET.get("term", "")
    q = Q()
    for term in query.split(" "):
        q &= Q(name__icontains=term)

    # Filter by correctly guessed taxonomy (if provided)
    order_filter = request.GET.get("order")
    family_filter = request.GET.get("family")
    genus_filter = request.GET.get("genus")

    if order_filter:
        q &= Q(order=order_filter)
    if family_filter:
        q &= Q(family=family_filter)
    if genus_filter:
        q &= Q(genus=genus_filter)

    # Pagination
    limit = int(request.GET.get("limit", 100))
    offset = int(request.GET.get("offset", 0))

    # Search for birds with names containing the query
    birds = Bird.objects.filter(birdregion__region__code=region_code).filter(q).order_by("name")
    # Fetch limit+1 to determine if there are more pages
    birds_page = list(birds[offset : offset + limit + 1])
    has_more = len(birds_page) > limit
    birds_page = birds_page[:limit]

    context = {
        "birds": birds_page,
        "has_more": has_more,
        "offset": offset,
        "limit": limit,
        "query": query,
        "order_filter": order_filter,
        "family_filter": family_filter,
        "genus_filter": genus_filter,
    }

    return render(request, "birdle/bird_suggestions.html", context)


@register.simple_tag
def get_regions():
    region_dict = {
        "world": "World",
        "lower48": "USA Lower 48",
        "na": "North America",
        "ca": "Central America",
        "sa": "South America",
        "eu": "Europe",
        "af": "Africa",
        "as": "Asia",
        "aut": "Australia and Territories",
    }
    return region_dict


@register.simple_tag(takes_context=True)
def current_region_code(context):
    """Get current region code from session."""
    request = context.get("request")
    if request:
        return request.session.get("region_code", "world")
    return "world"


@register.filter
def region_name(code):
    """Convert region code to display name."""
    return get_regions().get(code, "World")


def region(request):
    region_code = request.htmx.trigger_name

    # Validate region code
    regions = get_regions()
    if region_code not in regions:
        raise Http404("Region not found")

    request.session["region_code"] = region_code

    # Preserve the current page path when changing regions
    current_url = request.headers.get("HX-Current-URL", "")
    path = urlparse(current_url).path

    # Extract the page suffix (e.g., "stats/") from the current path
    # Path format: /{region_code}/stats/ or /stats/ or /
    path_parts = path.strip("/").split("/", 1)
    if path_parts[0] in regions:
        # Path has region prefix, get the rest
        suffix = path_parts[1] if len(path_parts) > 1 else ""
    else:
        # Path has no region prefix
        suffix = path_parts[0] if path_parts[0] else ""

    redirect_path = f"/{region_code}/{suffix}/" if suffix else f"/{region_code}/"
    redirect_path = redirect_path.replace("//", "/")

    return HttpResponse(
        regions[region_code],  # Return display name for dropdown
        headers={"HX-Redirect": redirect_path},
    )


def get_hint_data(guess_count, bird, is_winner=False):
    """Generate hint information based on current guess count, bird, and win status."""
    if guess_count < 3:
        return {"show": False, "title": "", "message": ""}

    if guess_count == 6 or is_winner:
        return {
            "show": True,
            "title": "You want a hint?",
            "message": "The game's over. Go outside.",
        }
    elif guess_count == 5:
        return {
            "show": True,
            "title": "One final hint?",
            "message": f"My name starts with '{bird.name[:3]}'.",
        }
    elif guess_count == 4:
        return {
            "show": True,
            "title": "Want another hint?",
            "message": f"My genus is '{bird.genus}'.",
        }
    else:  # guess_count == 3
        return {
            "show": True,
            "title": "Want a hint?",
            "message": f"I'm in the {bird.family} family.",
        }


def build_results_emojis(game, guesses):
    region = game.region
    answer = game.bird
    date = game.date
    results = []
    for guess in guesses:
        used_hint = "*" if guess.hint_used else ""
        taxonomy = guess.bird.compare(answer)
        row = "".join(["🐦" if i else "❌" for i in taxonomy]) + used_hint
        results.append(row)
    emojis = "\n".join(results)
    link = f"https://www.play-birdle.com/{region.code}/"
    return f"{region.name} Birdle\n{date}\n{emojis}\n{link}"


MIN_ACCOLADE_GAMES = 2


def get_taxonomy_stats(usergames):
    # Single pass over usergames so MIT-15 (best), MIT-16 (worst), and MIT-17 (species count)
    # can all reuse `won`/`species` from the same data instead of re-querying.
    taxonomy_stats = {
        "order": {},
        "family": {},
        "genus": {},
    }
    for usergame in usergames:
        if usergame.num_guesses == 0:
            continue
        bird = usergame.game.bird
        for level, name in (("order", bird.order), ("family", bird.family), ("genus", bird.genus)):
            entry = taxonomy_stats[level].setdefault(
                name, {"played": 0, "won": 0, "species": set(), "species_won": set()}
            )
            entry["played"] += 1
            if usergame.has_won:
                entry["won"] += 1
                entry["species_won"].add(bird.name)
            entry["species"].add(bird.name)
    return taxonomy_stats


def get_most_played_accolades(taxonomy_stats):
    most_played = {}
    for level, taxa in taxonomy_stats.items():
        eligible = {
            name: stats for name, stats in taxa.items() if stats["played"] >= MIN_ACCOLADE_GAMES
        }
        if not eligible:
            continue
        name = max(eligible, key=lambda name: eligible[name]["played"])
        most_played[level] = {"name": name, "count": eligible[name]["played"]}
    return most_played


def get_best_accolades(taxonomy_stats):
    best = {}
    for level, taxa in taxonomy_stats.items():
        eligible = {
            name: stats for name, stats in taxa.items() if stats["played"] >= MIN_ACCOLADE_GAMES
        }
        if not eligible:
            continue
        name = max(
            eligible,
            key=lambda name: (
                eligible[name]["won"] / eligible[name]["played"],
                eligible[name]["played"],
            ),
        )
        win_rate = eligible[name]["won"] / eligible[name]["played"]
        best[level] = {
            "name": name,
            "win_pct": f"{win_rate:.0%}",
            "games_won": eligible[name]["won"],
        }
    return best


def get_worst_accolades(taxonomy_stats):
    worst = {}
    for level, taxa in taxonomy_stats.items():
        eligible = {
            name: stats for name, stats in taxa.items() if stats["played"] >= MIN_ACCOLADE_GAMES
        }
        if not eligible:
            continue
        name = min(
            eligible,
            key=lambda name: (
                eligible[name]["won"] / eligible[name]["played"],
                -eligible[name]["played"],
            ),
        )
        win_rate = eligible[name]["won"] / eligible[name]["played"]
        worst[level] = {
            "name": name,
            "win_pct": f"{win_rate:.0%}",
            "games_won": eligible[name]["won"],
        }
    return worst


def get_world_traveler_status(username):
    # Not region-scoped (see MIT-6): spans every region, so query across all of them.
    usergames = (
        UserGame.objects.filter(user__username=username)
        .select_related("game__region")
        .annotate(
            has_won=Exists(
                Guess.objects.filter(usergame=OuterRef("pk"), bird=OuterRef("game__bird"))
            )
        )
    )
    wins_by_date = {}
    for usergame in usergames:
        if usergame.has_won:
            wins_by_date.setdefault(usergame.game.date, set()).add(usergame.game.region.code)
    all_regions = set(get_regions().keys())
    achieved_dates = sorted(
        date for date, regions in wins_by_date.items() if all_regions <= regions
    )
    return {
        "earned": bool(achieved_dates),
        "count": len(achieved_dates),
        "latest": achieved_dates[-1] if achieved_dates else None,
    }


def get_species_identified(taxonomy_stats, limit=5):
    # For each taxonomy level, the top `limit` taxa by count of distinct species won,
    # sorted descending. No MIN_ACCOLADE_GAMES threshold: a single correctly-identified
    # species is a countable fact regardless of sample size.
    species_identified = {}
    for level, taxa in taxonomy_stats.items():
        counts = [
            (name, len(data["species_won"])) for name, data in taxa.items() if data["species_won"]
        ]
        counts.sort(key=lambda item: item[1], reverse=True)
        species_identified[level] = counts[:limit]
    return species_identified


CATCH_EM_ALL_TIERS = [(1.0, "Bird"), (0.75, "Chick"), (0.5, "Hatchling")]


def get_taxon_species_totals(region_code, level):
    # Total distinct species per taxon name, among birds available in this region.
    # Cached: this is static reference data that only changes via management commands
    # (import_bird_species, update_birdregions). Cache must be cleared manually (or the
    # TTL shortened) if that data changes and stats should reflect it immediately.
    cache_key = f"taxon_species_totals:{region_code}:{level}"
    totals = cache.get(cache_key)
    if totals is None:
        rows = (
            Bird.objects.filter(birdregion__region__code=region_code)
            .values(level)
            .annotate(total=Count("species_code", distinct=True))
        )
        totals = {row[level]: row["total"] for row in rows}
        cache.set(cache_key, totals, timeout=60 * 60 * 24)
    return totals


def get_catch_em_all_progress(taxonomy_stats, region_code):
    progress = {}
    for level in ("family", "genus"):
        totals = get_taxon_species_totals(region_code, level)
        entries = []
        for name, data in taxonomy_stats[level].items():
            total = totals.get(name)
            if not total:
                continue
            pct = len(data["species_won"]) / total
            tier = next(
                (label for threshold, label in CATCH_EM_ALL_TIERS if pct >= threshold), None
            )
            if tier is None:
                continue
            entries.append(
                (pct, {"name": name, "tier": tier, "won": len(data["species_won"]), "total": total})
            )
        entries.sort(key=lambda e: (-e[0], e[1]["name"]))
        progress[level] = [entry for _, entry in entries]
    return progress


def error_404(request, exception):
    return render(request, "404.html", status=404)


def error_500(request):
    return render(request, "500.html", status=500)
