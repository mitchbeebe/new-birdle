import calendar
import json
import random
import re
import requests
import requests.adapters
from bs4 import BeautifulSoup
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.shortcuts import redirect, render
from urllib.parse import quote, unquote, urlparse
from django.contrib.auth.models import User
from .models import (
    Bird,
    CustomRegion,
    FriendInvite,
    Friendship,
    Guess,
    Game,
    Membership,
    UserGame,
    Image,
    BirdRegion,
    Region,
)
from .forms import BirdRegionForm, CustomRegionForm, UsernameForm, practice_pool
from . import ebird
from . import friends as friends_lib
from . import premium as premium_lib
from .signals import merge_anonymous_history
from .premium import premium_required
from .accolades import detailed_stats
from . import leaderboards
from django.core.cache import cache
from django.db.models import Count, Exists, OuterRef, Q
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseRedirect,
    JsonResponse,
)
from django.urls import reverse
from django.template.loader import render_to_string
from django.template.defaulttags import register
import logging
import pytz
from datetime import date, datetime, timezone
from random import choices
from pandas import date_range

logger = logging.getLogger(__name__)

# Public code for a premium user's custom region; resolved per user to ``near-me-<pk>``.
CUSTOM_REGION_CODE = "near-me"
CUSTOM_REGION_NAME = "Near me"
# Paths under /<region>/ that the region switcher preserves when changing regions.
REGION_PAGE_SUFFIXES = {"stats", "archive", "leaderboard"}


def custom_region_db_code(user) -> str:
    return f"{CUSTOM_REGION_CODE}-{user.pk}"


def resolve_region_code(request, region_code):
    """Map a public region code to the Region.code used in the database.

    Fixed regions pass through. ``custom`` resolves to the logged-in premium user's own
    region; otherwise returns a redirect (login / premium) or raises 404.
    """
    if region_code in get_regions():
        return region_code
    if region_code != CUSTOM_REGION_CODE:
        raise Http404("Region not found")
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if not premium_lib.is_premium(request.user):
        return redirect("premium")
    custom = CustomRegion.objects.filter(user=request.user).first()
    if custom is None or custom.species_count == 0:
        # Not set up yet: send them to the profile to build it.
        return redirect("profile")
    return custom.region.code


def random_bird(region_code="world"):
    # Randomly draw a bird from the region provided, excluding birds
    # used in the most recent games for that region so no species repeats
    # until the rest of the pool has cycled through.
    region = Region.objects.get(code=region_code)
    birdregions = BirdRegion.objects.filter(region=region)
    pool_size = birdregions.count()

    cooldown = max(pool_size - 1, 0)
    recent_bird_ids = (
        Game.objects.filter(region=region)
        .order_by("-date")
        .values_list("bird_id", flat=True)[:cooldown]
    )
    candidates = birdregions.exclude(bird_id__in=recent_bird_ids)

    count = candidates.count()
    idx = random.randrange(0, count)
    bird = candidates[idx].bird
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
        game = _create_game(region, today)
    return game


def _create_game(region, game_date):
    """Draw a bird with at least two images and create the game for ``game_date``."""
    while True:
        bird = random_bird(region.code)
        imgs = get_bird_images(bird)
        if len(imgs) >= 2:
            game, _ = Game.objects.update_or_create(
                date=game_date, region=region, defaults={"bird": bird}
            )
            return game


def _stats_cache_key(username, region_code):
    return f"stats:{username}:{region_code}"


def daily_bird(request, region_code=None):
    # Redirect to regional URL if no region code provided
    if not region_code:
        region_code = request.session.get("region_code", "world")
        return redirect("daily_bird_region", region_code=region_code)

    # Validate region code
    resolved = resolve_region_code(request, region_code)
    if isinstance(resolved, HttpResponse):
        return resolved
    request.session["region_code"] = region_code
    region_code = resolved

    user_tz = get_user_timezone(request)
    game = todays_game(region_code, tz=user_tz)
    user = _session_user(request)
    usergame, _ = UserGame.objects.get_or_create(user=user, game=game)
    return _play(request, game, usergame, region_code)


def _session_user(request):
    """The player: the logged-in account, else the anonymous user tracked by this browser.

    ``user_id`` is the pre-accounts anonymous id some browsers still send from localStorage.
    It must never override a logged-in account, but any history it points at is folded in.
    """
    old_username = request.POST.get("user_id")
    if request.user.is_authenticated:
        user = request.user
        for stale in {old_username, request.session.get("username")} - {None, "", user.username}:
            merge_anonymous_history(request, user, anon_username=stale)
    else:
        username = old_username or request.session.get(
            "username", int(datetime.now().timestamp() * 100)
        )
        user, _ = User.objects.get_or_create(username=username)
    request.session["username"] = user.username
    return user


def _play(request, game, usergame, region_code, archive=False):
    user = usergame.user
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
            "archive": archive,
            "game_date": game.date,
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
            cache.delete(_stats_cache_key(user.username, region_code))
            leaderboards.invalidate(region_code)

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


def _render_profile(request, form=None, region_form=None, saved=False):
    custom = CustomRegion.objects.filter(user=request.user).first()
    if form is None:
        form = UsernameForm(instance=request.user)
    if region_form is None:
        region_form = CustomRegionForm(instance=custom)
    context = {
        "form": form,
        "saved": saved,
        "custom_region": custom,
        "region_form": region_form,
        "ebird_enabled": settings.EBIRD_ENABLED,
    }
    # The custom region form posts via htmx and swaps just its own section.
    template = "birdle/_custom_region.html" if request.htmx else "birdle/profile.html"
    return render(request, template, context)


@login_required
def profile(request):
    saved = False
    form = None
    if request.method == "POST":
        form = UsernameForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            request.session["username"] = request.user.username
            saved = True
    return _render_profile(request, form=form, saved=saved)


@premium_required
@require_http_methods(["POST"])
def custom_region(request):
    """Create/update the user's custom region and (re)build its species pool."""
    custom = CustomRegion.objects.filter(user=request.user).first()
    region_form = CustomRegionForm(request.POST, instance=custom)
    if not region_form.is_valid():
        return _render_profile(request, region_form=region_form)
    custom = region_form.save(commit=False)
    if custom.region_id is None:
        custom.user = request.user
        # get_or_create: a Region can outlive its CustomRegion (e.g. after a migration rollback).
        custom.region, _ = Region.objects.get_or_create(
            code=custom_region_db_code(request.user), defaults={"name": CUSTOM_REGION_NAME}
        )
    custom.save()
    try:
        ebird.build_pool(custom)
    except ebird.EbirdError as exc:
        region_form.add_error(None, str(exc))
        return _render_profile(request, region_form=region_form)
    cache.delete(_stats_cache_key(request.user.username, custom.region.code))
    if request.htmx:
        return _render_profile(request)
    return redirect("profile")


@premium_required
@require_http_methods(["POST"])
def custom_region_delete(request):
    custom = CustomRegion.objects.filter(user=request.user).first()
    if custom is not None:
        # Cascades to the CustomRegion, its BirdRegion pool, and its games.
        custom.region.delete()
    if request.session.get("region_code") == CUSTOM_REGION_CODE:
        request.session["region_code"] = "world"
    if request.htmx:
        return _render_profile(request)
    return redirect("profile")


def _validate_region(request, region_code):
    """Validate a public region code; returns the Region.code to query, or a redirect."""
    resolved = resolve_region_code(request, region_code)
    if isinstance(resolved, HttpResponse):
        return resolved
    request.session["region_code"] = region_code
    return resolved


def _today(tz):
    return datetime.now(timezone.utc).astimezone(tz).date()


def _past_game_or_404(region_code, date_str, tz, create_from=None):
    """Look up a past game; for a near-me region, create it on demand back to ``create_from``.

    A near-me region has a single player, so days they didn't open have no Game row yet.
    """
    try:
        game_date = date.fromisoformat(date_str)
    except ValueError:
        raise Http404("Invalid date")
    if game_date >= _today(tz):
        raise Http404("Game not yet in the archive")
    try:
        return Game.objects.select_related("bird", "region").get(
            date=game_date, region__code=region_code
        )
    except Game.DoesNotExist:
        if create_from is None or game_date < create_from:
            raise Http404("No game for that date")
        return _create_game(Region.objects.get(code=region_code), game_date)


def _custom_region_start(request, db_code, tz):
    """Date a near-me region's pool was built (in the user's tz), or None for fixed regions."""
    if not db_code.startswith(f"{CUSTOM_REGION_CODE}-"):
        return None
    custom = CustomRegion.objects.filter(user=request.user).first()
    if custom is None or custom.built_at is None:
        return None
    return custom.built_at.astimezone(tz).date()


def _month_param(value, today):
    try:
        return datetime.strptime(value, "%Y-%m").date().replace(day=1)
    except TypeError, ValueError:
        return today.replace(day=1)


def _add_months(month, n):
    total = month.year * 12 + (month.month - 1) + n
    return date(total // 12, total % 12 + 1, 1)


@premium_lib.premium_required
def archive(request, region_code):
    db_code = _validate_region(request, region_code)
    if isinstance(db_code, HttpResponse):
        return db_code
    user_tz = get_user_timezone(request)
    today = _today(user_tz)
    month = _month_param(request.GET.get("month"), today)
    first_game = Game.objects.filter(region__code=db_code).order_by("date").first()
    first_date = first_game.date if first_game else today
    playable_from = _custom_region_start(request, db_code, user_tz)
    if playable_from is not None:
        first_date = min(first_date, playable_from)
    first_month = first_date.replace(day=1)
    month = min(max(month, first_month), today.replace(day=1))

    games = Game.objects.filter(
        region__code=db_code,
        date__gte=month,
        date__lt=min(_add_months(month, 1), today),
    ).select_related("bird")
    by_date = {game.date: game for game in games}
    usergames = (
        UserGame.objects.filter(user=request.user, game__in=games)
        .select_related("game")
        .annotate(
            num_guesses=Count("guess"),
            has_won=Exists(
                Guess.objects.filter(usergame=OuterRef("pk"), bird=OuterRef("game__bird"))
            ),
        )
    )
    by_game = {usergame.game.pk: usergame for usergame in usergames}

    def day_cell(day):
        if day == 0:
            return None
        game_date = month.replace(day=day)
        game = by_date.get(game_date)
        if game is None:
            # Near-me days without a game yet are still playable; created on click.
            if playable_from is not None and playable_from <= game_date < today:
                return {"day": day, "date": game_date, "result": "Not played", "finished": False}
            return {"day": day}
        usergame = by_game.get(game.pk)
        if usergame is None or usergame.num_guesses == 0:
            result = "Not played"
        elif usergame.has_won:
            result = "Win"
        elif usergame.num_guesses >= 6:
            result = "Loss"
        else:
            result = "In progress"
        finished = result in ("Win", "Loss")
        return {
            "day": day,
            "date": game_date,
            "bird": game.bird.name if finished else None,
            "result": result,
            "finished": finished,
        }

    weeks = [
        [day_cell(d) for d in week] for week in calendar.monthcalendar(month.year, month.month)
    ]

    context = {
        "region_code": region_code,
        "month": month,
        "weeks": weeks,
        "prev_month": _add_months(month, -1) if month > first_month else None,
        "next_month": _add_months(month, 1) if month < today.replace(day=1) else None,
    }
    return render(request, "birdle/archive.html", context)


@premium_lib.premium_required
def archive_game(request, region_code, date):
    db_code = _validate_region(request, region_code)
    if isinstance(db_code, HttpResponse):
        return db_code
    user_tz = get_user_timezone(request)
    game = _past_game_or_404(
        db_code, date, user_tz, create_from=_custom_region_start(request, db_code, user_tz)
    )
    user = _session_user(request)
    usergame, _ = UserGame.objects.get_or_create(
        user=user, game=game, defaults={"is_archive": True}
    )
    return _play(request, game, usergame, region_code, archive=True)


@premium_lib.premium_required
def friends(request):
    accepted = Friendship.objects.filter(
        Q(from_user=request.user) | Q(to_user=request.user), status=Friendship.ACCEPTED
    ).select_related("from_user", "to_user")
    friend_rows = [
        (f, f.to_user if f.from_user_id == request.user.pk else f.from_user) for f in accepted
    ]
    friend_rows.sort(key=lambda row: row[1].username.lower())
    return render(
        request,
        "birdle/friends.html",
        {
            "friends": friend_rows,
            "incoming": friends_lib.pending_incoming(request.user),
            "outgoing": friends_lib.pending_outgoing(request.user),
            "invite_url": request.build_absolute_uri(
                reverse("friend_join", args=[friends_lib.invite_for(request.user).token])
            ),
        },
    )


@premium_lib.premium_required
@require_http_methods(["POST"])
def friend_invite_reset(request):
    friends_lib.reset_invite(request.user)
    messages.info(request, "Invite link reset. The old link no longer works.")
    return redirect("friends")


@premium_lib.premium_required
@require_http_methods(["GET", "POST"])
def friend_join(request, token):
    invite = FriendInvite.objects.filter(token=token).select_related("user").first()
    if invite is None:
        raise Http404
    if request.method == "GET":
        return render(request, "birdle/friend_join.html", {"inviter": invite.user})
    try:
        friends_lib.send_request(request.user, invite.user, accepted=True)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect("friends")
    messages.success(request, f"You and {invite.user.username} are now friends.")
    return redirect("friends")


@premium_lib.premium_required
@require_http_methods(["POST"])
def friend_request(request):
    username = request.POST.get("username", "").strip()
    # Anonymous players get auto-generated numeric usernames and no email; they aren't
    # addable, and we report them the same as a missing user so nothing leaks.
    target = (
        User.objects.filter(username__iexact=username)
        .exclude(email="", username__regex=r"^\d+$")
        .first()
    )
    if target is None:
        messages.error(request, "User not found.")
        return redirect("friends")
    try:
        friendship = friends_lib.send_request(request.user, target)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect("friends")
    if friendship.status == Friendship.ACCEPTED:
        messages.success(request, f"You and {target.username} are now friends.")
    else:
        messages.success(request, f"Friend request sent to {target.username}.")
    return redirect("friends")


@premium_lib.premium_required
@require_http_methods(["POST"])
def friend_accept(request, pk):
    friendship = Friendship.objects.filter(pk=pk, status=Friendship.PENDING).first()
    if friendship is None:
        raise Http404
    if friendship.to_user_id != request.user.pk:
        return HttpResponseForbidden()
    friendship.status = Friendship.ACCEPTED
    friendship.save(update_fields=["status"])
    messages.success(request, f"You and {friendship.from_user.username} are now friends.")
    return redirect("friends")


@premium_lib.premium_required
@require_http_methods(["POST"])
def friend_decline(request, pk):
    friendship = Friendship.objects.filter(pk=pk, status=Friendship.PENDING).first()
    if friendship is None:
        raise Http404
    if friendship.to_user_id != request.user.pk:
        return HttpResponseForbidden()
    friendship.delete()
    messages.info(request, "Request declined.")
    return redirect("friends")


@premium_lib.premium_required
@require_http_methods(["POST"])
def friend_remove(request, pk):
    friendship = Friendship.objects.filter(pk=pk, status=Friendship.ACCEPTED).first()
    if friendship is None:
        raise Http404
    if request.user.pk not in (friendship.from_user_id, friendship.to_user_id):
        return HttpResponseForbidden()
    friendship.delete()
    messages.info(request, "Friend removed.")
    return redirect("friends")


def stats(request, region_code=None):
    # Redirect to regional URL if no region code provided
    if not region_code:
        region_code = request.session.get("region_code", "world")
        return redirect("stats_region", region_code=region_code)

    # Validate region code
    resolved = resolve_region_code(request, region_code)
    if isinstance(resolved, HttpResponse):
        return resolved
    request.session["region_code"] = region_code
    region_code = resolved

    username = request.session.get("username")
    user_tz = get_user_timezone(request)
    premium = premium_lib.is_premium(request.user)
    cache_key = _stats_cache_key(username, region_code) if username else None
    stats = cache.get(cache_key) if cache_key else None
    # A cached block computed before the user went premium lacks the detailed section.
    if stats is not None and premium and "detailed" not in stats:
        stats = None
    # Retrieve the user's guess history from the database
    if username and stats is None:
        usergames = (
            UserGame.objects.filter(
                user__username=username, game__region__code=region_code, is_archive=False
            )
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

        stats = {
            "games_played": games_played,
            "games_won": games_won,
            "win_pct": f"{win_pct:.0%}",
            "guess_freq": json.dumps(guess_dist),
            "history": json.dumps(history),
            "current_streak": current_streak,
            "best_streak": best_streak,
        }
        if premium:
            stats["detailed"] = detailed_stats(
                request.user, region_code, user_tz, best_streak, get_regions()
            )
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
        }
    # Render the guess history template with the data
    assert stats is not None
    context = {**stats, "premium": premium}
    if not premium:
        context.pop("detailed", None)
    return render(request, "birdle/stats.html", context)


PERIODS = {"week": "This week", "month": "This month", "all": "All time"}
SCOPES = {"friends": "Friends", "all": "Everyone"}


@premium_lib.premium_required
def leaderboard(request, region_code=None):
    # Redirect to regional URL if no region code provided
    if not region_code:
        region_code = request.session.get("region_code", "world")
        return redirect("leaderboard_region", region_code=region_code)

    db_code = _validate_region(request, region_code)
    if isinstance(db_code, HttpResponse):
        return db_code

    period = request.GET.get("period", "week")
    if period not in PERIODS:
        period = "week"
    scope = request.GET.get("scope", "friends")
    if scope not in SCOPES:
        scope = "friends"
    context = {
        "boards": [],
        "period": period,
        "period_label": PERIODS[period].lower(),
        "periods": PERIODS,
        "scope": scope,
        "scopes": SCOPES,
        # A near-me region has a single player, so there is nobody to rank against.
        "single_player": region_code == CUSTOM_REGION_CODE,
    }
    if context["single_player"]:
        return render(request, "birdle/leaderboard.html", context)

    today = datetime.now(timezone.utc).astimezone(get_user_timezone(request)).date()
    start, end = leaderboards.period_bounds(period, today)

    boards = context["boards"]
    for key, title, rows in [
        ("played", "Games played", leaderboards.played(db_code, start, end)),
        ("wins", "Weighted wins", leaderboards.weighted_wins(db_code, start, end)),
        ("streak", "Current streak", leaderboards.streaks(db_code, today)),
    ]:
        if scope == "friends":
            ids = friends_lib.friend_ids(request.user) | {request.user.pk}
            usernames = dict(User.objects.filter(pk__in=ids).values_list("pk", "username"))
            rows = leaderboards.among(rows, ids, usernames)
        boards.append(
            {
                "key": key,
                "title": title,
                "rows": rows[: leaderboards.TOP_N],
                "total": len(rows),
                "rank": leaderboards.rank_of(rows, request.user.pk),
            }
        )
    return render(request, "birdle/leaderboard.html", context)


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

            if decoded_region == "Any" and decoded_family == "Any":
                birds = Bird.objects.all()
            else:
                pool = practice_pool(request.user, decoded_region, decoded_family)
                birds = [x.bird for x in pool.select_related("bird")]
            if not birds:
                raise Http404("No birds to practice with")

            birds_choices = choices(birds, k=4)
            bird = choices(birds_choices, k=1)[0]
            imgs = get_bird_images(bird=bird)
            options = list(set([bird.name for bird in birds_choices]))
            data.update({"imgs": imgs, "options": options, "answer": bird})
            form = BirdRegionForm(
                initial={"region": decoded_region, "family": decoded_family}, user=request.user
            )
        else:
            form = BirdRegionForm(user=request.user)
        return render(request, "birdle/practice.html", {"form": form, **data})
    elif request.method == "POST":
        form = BirdRegionForm(request.POST, user=request.user)
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
    if region_code == CUSTOM_REGION_CODE and request.user.is_authenticated:
        region_code = custom_region_db_code(request.user)

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


@register.simple_tag
def get_nav_regions():
    """Regions shown in the nav dropdown; the template disables custom for non-members."""
    return {CUSTOM_REGION_CODE: CUSTOM_REGION_NAME, **get_regions()}


@register.simple_tag
def google_login_enabled():
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID)


@register.simple_tag(takes_context=True)
def is_premium(context):
    return premium_lib.is_premium(context["user"])


@register.simple_tag(takes_context=True)
def friend_request_count(context):
    user = context["user"]
    if not user.is_authenticated:
        return 0
    return friends_lib.pending_incoming(user).count()


@register.filter
def add_class(field, css_class):
    return field.as_widget(attrs={"class": css_class})


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
    if code == CUSTOM_REGION_CODE:
        return CUSTOM_REGION_NAME
    return get_regions().get(code, "World")


def region(request):
    region_code = request.htmx.trigger_name

    # Validate region code
    regions = get_nav_regions()
    resolved = resolve_region_code(request, region_code)
    if isinstance(resolved, HttpResponse):
        # htmx would swap a followed redirect into the nav; tell it to navigate instead.
        return HttpResponse(headers={"HX-Redirect": resolved["Location"]})

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

    # Only regional sub-pages carry over; anything else (e.g. /accounts/profile/) goes home.
    if suffix not in REGION_PAGE_SUFFIXES:
        suffix = ""
    redirect_path = f"/{region_code}/{suffix}/" if suffix else f"/{region_code}/"
    redirect_path = redirect_path.replace("//", "/")

    return HttpResponse(
        regions[region_code],  # Return display name for dropdown
        headers={"HX-Redirect": redirect_path},
    )


def premium(request):
    membership = None
    if request.user.is_authenticated:
        membership = Membership.objects.filter(user=request.user).first()
    return render(
        request,
        "birdle/premium.html",
        {
            "membership": membership,
            "premium": membership is not None and membership.is_active,
            "stripe_enabled": settings.STRIPE_ENABLED,
        },
    )


@login_required
@require_http_methods(["POST"])
def premium_checkout(request):
    if not settings.STRIPE_ENABLED:
        return HttpResponse("Subscriptions aren't available yet.", status=503)
    membership, _ = Membership.objects.get_or_create(user=request.user)
    if not membership.stripe_customer_id:
        membership.stripe_customer_id = premium_lib.create_customer(request.user)
        membership.save(update_fields=["stripe_customer_id"])
    # Don't let a returning customer create a second subscription; sync the
    # existing one (covers a missed webhook) and send them to the status page.
    existing = premium_lib.find_subscription(membership.stripe_customer_id)
    if existing is not None:
        _apply_subscription(membership, existing)
        return redirect("premium")
    url = premium_lib.create_checkout_session(
        membership.stripe_customer_id,
        request.user.pk,
        request.build_absolute_uri(reverse("premium_success")),
        request.build_absolute_uri(reverse("premium")),
    )
    return HttpResponseRedirect(url, status=303)


@login_required
def premium_success(request):
    return render(request, "birdle/premium_success.html")


@login_required
@require_http_methods(["POST"])
def premium_portal(request):
    membership = Membership.objects.filter(user=request.user).first()
    if not settings.STRIPE_ENABLED or membership is None or not membership.stripe_customer_id:
        return HttpResponse("No subscription to manage.", status=400)
    url = premium_lib.create_portal_session(
        membership.stripe_customer_id, request.build_absolute_uri(reverse("premium"))
    )
    return HttpResponseRedirect(url, status=303)


def _subscription_period_end(subscription):
    # Newer Stripe API versions moved current_period_end from the subscription
    # onto its items.
    ts = subscription.get("current_period_end")
    if ts is None:
        items = subscription.get("items") or {}
        data = items.get("data") or []
        if data:
            ts = data[0].get("current_period_end")
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _apply_subscription(membership, subscription):
    membership.stripe_subscription_id = subscription.get("id") or membership.stripe_subscription_id
    membership.status = subscription.get("status") or ""
    membership.current_period_end = _subscription_period_end(subscription)
    membership.save(update_fields=["stripe_subscription_id", "status", "current_period_end"])


@csrf_exempt
@require_http_methods(["POST"])
def stripe_webhook(request):
    try:
        event = premium_lib.construct_event(
            request.body, request.META.get("HTTP_STRIPE_SIGNATURE", "")
        )
    except Exception:
        return HttpResponse("Invalid signature", status=400)

    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        user = User.objects.filter(pk=obj.get("client_reference_id") or None).first()
        if user is None:
            logger.warning("Stripe checkout completed for unknown user %r", obj.get("id"))
            return HttpResponse(status=200)
        membership, _ = Membership.objects.get_or_create(user=user)
        membership.stripe_customer_id = obj.get("customer") or ""
        membership.stripe_subscription_id = obj.get("subscription") or ""
        membership.save(update_fields=["stripe_customer_id", "stripe_subscription_id"])
    elif event_type in {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        membership = Membership.objects.filter(stripe_customer_id=obj.get("customer")).first()
        if membership is None:
            membership = Membership.objects.filter(stripe_subscription_id=obj.get("id")).first()
        if membership is None:
            logger.warning("Stripe subscription event for unknown customer %r", obj.get("customer"))
            return HttpResponse(status=200)
        _apply_subscription(membership, obj)

    return HttpResponse(status=200)


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
    # A custom region is private to its owner, so point others at the premium page instead.
    is_custom = region.code.startswith(f"{CUSTOM_REGION_CODE}-")
    link = f"https://www.play-birdle.com/{'premium' if is_custom else region.code}/"
    return f"{region.name} Birdle\n{date}\n{emojis}\n{link}"


def error_404(request, exception):
    return render(request, "404.html", status=404)


def error_500(request):
    return render(request, "500.html", status=500)
