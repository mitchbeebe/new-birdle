import json
import random
import re
import requests
from bs4 import BeautifulSoup
from django.shortcuts import redirect, render
from urllib.parse import quote, unquote
from .models import Bird, Guess, User, Game, UserGame, Image, BirdRegion, Region
from .forms import BirdRegionForm
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.template.defaulttags import register
import pytz
from datetime import datetime
from random import choices
from pandas import date_range


def random_bird(region="World"):
    # Randomly draw a bird from the region provided
    region = Region.objects.get(name=region)
    birdregions = BirdRegion.objects.filter(region=region)
    count = birdregions.count()
    idx = random.randrange(0, count)
    bird = birdregions[idx].bird
    return bird


def todays_game(region="World"):
    # Get current date in Eastern time
    tz = pytz.timezone('US/Eastern')
    today = datetime.utcnow().astimezone(tz).strftime("%Y-%m-%d")
    region = Region.objects.get(name=region)
    try:
        # Assumes an already created game is valid
        game = Game.objects.get(date=today, region=region)
    except Game.DoesNotExist:
        # Randomly select a bird
        bird = random_bird(region)
        imgs = get_bird_images(bird)

        # Create game if at least two images
        if len(imgs) >= 2:
            game, _ = Game.objects.update_or_create(
                date=today,
                region=region,
                bird=bird
            )
        else:
            # Redraw bird if fewer than 2 images
            todays_game(region)
    return game


def daily_bird(request):
    game = todays_game(request.session.get("region", "World"))
    
    # Get user if available
    old_username = request.POST.get('user_id')
    if old_username:
        username = old_username
    else:
        username = request.session.get('username', int(datetime.now().timestamp()*100))
    user, _ = User.objects.get_or_create(username=username)
    request.session["username"] = user.username

    usergame, _ = UserGame.objects.get_or_create(user=user, game=game)
    
    if request.method == "GET":
        imgs = get_bird_images(bird=game.bird, game=game)
        # Get past guesses
        guesses = Guess.objects.filter(usergame=usergame).order_by('guessed_at')
        # Convert guesses to Birds
        bird_guesses = [guess.bird for guess in guesses]

        context = {
            "imgs": imgs,
            "bird": game.bird,
            "is_winner": usergame.is_winner, 
            "guesses": [{**b.info(), "correctness": b.compare(game.bird)} for b in bird_guesses],
            "guess_count": usergame.guess_count,
            "emojis": build_results_emojis(game, guesses)
        }
        return render(request, 'birdle/daily_bird.html', context)
    
    elif request.method == "POST":
        # Get the Bird the user guessed
        try:
            guess = Bird.objects.get(name=request.POST.get('guess-input'))
        except (KeyError, Bird.DoesNotExist):
            error_msg = "That bird doesn't exist!"
            return HttpResponse(error_msg, status=400)
        
        # Check if they still have guesses and have not won already
        if usergame.guess_count < 6 and not usergame.is_winner:
            # Add the user's guess to the database
            Guess.objects.create(
                usergame=usergame,
                bird=guess,
                hint_used=request.POST.get('hint_used') == 'true'
            )
        
        # Get all user guesses
        guesses = Guess.objects.filter(usergame=usergame).order_by('guessed_at')

        # Convert guesses to Birds
        bird_guesses = [guess.bird for guess in guesses]

        context = {
            "is_winner": usergame.is_winner,
            "new_guess": render_to_string("birdle/guess.html", {**guess.info(), "correctness": guess.compare(game.bird)}),
            "guess_count": guesses.count(),
            "emojis": build_results_emojis(game, guesses)
        }
        return JsonResponse(context)


def stats(request):
    username = request.session.get("username")
    region = request.session.get("region", "World")
    # Retrieve the user's guess history from the database
    if username:
        usergames = UserGame.objects.filter(user__username=username, game__region__name=region)
        today = datetime.utcnow().astimezone(pytz.timezone('US/Eastern')).date()
        first_game = min([usergame.game.date for usergame in usergames] + [today])
        games = Game.objects.filter(date__gte=first_game, date__lte=today, region__name=region).order_by("date")
        
        # User stats
        games_played = len([game for game in usergames if game.guess_count > 0])
        wins = [game for game in usergames if game.is_winner]
        games_won = len(wins)
        win_pct = games_won/games_played if games_played > 0 else 0
        guess_counts = [game.guess_count for game in wins if game.guess_count > 0]
        guess_dist = [
            {"guesses": i, "count": guess_counts.count(i)} for i in range(1, 7)
        ]

        def result(game):
            if game.guess_count == 0:
                result = "Did not play"
            elif game.is_winner:
                result = "Win"
            else:
                result = "Loss"
            return result
        
        game_results = {
            str(usergame.game.date): result(usergame) for usergame in usergames
        }

        # Create daily data for calendar view
        date_list = date_range(first_game, today, freq='D').map(lambda x: x.strftime("%Y-%m-%d"))
        results = [game_results.get(date, "Did not play") for date in date_list]
        birds = [game.bird.name for game in games]
        history = [
            {"Date": date, "Result": result, "Bird": bird} for date, result, bird in zip(date_list, results, birds)
        ]
        
        # Hide todays result if they're still playing and haven't won
        todays_result = usergames.filter(game__date=today)
        if todays_result:
            history = history[0:-1] if todays_result[0].guess_count < 6 and not todays_result[0].is_winner else history
        else:
            history = history[0:-1]

        # Calculate streak
        streaks = []
        streak = 0
        for result in results:
            if result == 'Win':
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
            "best_streak": best_streak
        }
    else:
        stats = {
            "games_played": 0,
            "games_won": 0,
            "win_pct": "N/A",
            "guess_freq": json.dumps([]),
            "history": json.dumps([]),
            "current_streak": 0,
            "best_streak": 0
        }
    # Render the guess history template with the data
    return render(request, 'birdle/stats.html', stats)


def info(request):
    return render(request, 'birdle/info.html')


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
            data.update({
                "imgs": imgs,
                "options": options,
                "answer": bird
            })
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
        ebird_sesh.mount('https://', ebird_adapter)
        
        # Get and parse the bird page on eBird
        response = ebird_sesh.get(bird.url)
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Get divs that contain images and captions
        items = soup.find_all("div", class_="CarouselResponsive-slide--photo")

        # Get labels and photographer from the image alt text
        alt_labels = [x.find("img", class_="Species-media-image")["alt"] for x in items]
        raw_labels = [l.split(" - ")[0] for l in alt_labels]
        labels = [label or "Version " + str(i+1) for i, label in enumerate(raw_labels)]
        photographer = [p.split(" - ")[1] for p in alt_labels]

        # Get the image url
        url_srcs = [x.find("img")["srcset"] for x in items]
        pattern = "https:\/\/cdn.download\.ams.birds\.cornell\.edu\/api\/v1\/asset\/\d+\/1800"
        urls = [re.search(pattern, src).group() for src in url_srcs]
        
        # Zip everything together
        img_list = list(zip(labels, urls, photographer))

        # Get the range, if it exists
        range_req = requests.get(f"https://birdsoftheworld.org/bow/species/{bird.species_code}/cur/introduction")
        range_soup = BeautifulSoup(range_req.content, "html.parser")
        try:
            range_url = range_soup.find_all("figure", class_="Figure")[0].find("a")["data-asset-src"]
        except IndexError:
            HttpResponse("Range not found", status=400)
        else:
            img_list.append(("Range", range_url, None))
        
        imgs = []
        for (label, url, photographer) in img_list:
            img, _ = Image.objects.update_or_create(url=url, label=label, photographer=photographer, bird=bird) 
            imgs.append(img)

        return imgs


def bird_autocomplete(request):
    # Only show birds in region
    region = request.session.get("region", "World")

    query = request.GET.get('term', '')
    q = Q()
    for term in query.split(" "):
        q &= Q(name__icontains=term)

    # Search for birds with names containing the query
    birds = Bird.objects.filter(birdregion__region__name=region).filter(q).order_by("name")
    
    # Return a list of bird names as the autocomplete options
    options = [bird.name for bird in birds]

    return JsonResponse(options, safe=False)


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
        "aut": "Australia and Territories"
        }
    return region_dict


def region(request):
    region = Region.objects.get(code=request.htmx.trigger_name)
    request.session["region"] = region.name
    return HttpResponse(request.session["region"], headers={"HX-Refresh": "true"})


def build_results_emojis(game, guesses):
    region = game.region.name
    answer = game.bird
    date = game.date
    results = []
    for guess in guesses:
        used_hint = "*" if guess.hint_used else ""
        taxonomy = guess.bird.compare(answer)
        row = "".join(["🐦" if i else "❌" for i in taxonomy]) + used_hint
        results.append(row)
    emojis = "\n".join(results)
    link = "https://www.play-birdle.com"
    return f"{region} Birdle\n{date}\n{emojis}\n{link}"


def error_404(request, exception):
    return render(request, '404.html', status=404)


def error_500(request):
    return render(request, '500.html', status=500)