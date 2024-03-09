import json
import requests
from bs4 import BeautifulSoup
from django.shortcuts import redirect, render
from urllib.parse import quote, unquote
from .models import Bird, Guess, User, Game, UserGame, Image, BirdRegion
from .forms import BirdRegionForm
from django.db.models import Q, F
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.contrib import messages
import pytz
from datetime import datetime
from random import choices
from pandas import date_range
from django.db.models import Min


def todays_game():
    tz = pytz.timezone('US/Eastern')
    today = datetime.utcnow().astimezone(tz).strftime("%Y-%m-%d")
    game = Game.objects.get(date=today)
    return game


def daily_bird(request):
    game = todays_game()
    
    # Get user if available
    old_username = request.POST.get('user_id')
    print(old_username)
    if old_username:
        username = old_username
    else:
        username = request.session.get('username', int(datetime.now().timestamp()*100))
    user, _ = User.objects.get_or_create(username=username)
    request.session["username"] = user.username

    usergame, _ = UserGame.objects.get_or_create(user=user, game=game)
    
    if request.method == "GET":
        imgs = get_bird_images(game.bird)
        # Get past guesses
        guesses = Guess.objects.filter(usergame=usergame)
        # Convert guesses to Birds
        bird_guesses = [guess.bird for guess in guesses]

        context = {
            "imgs": imgs,
            "bird": game.bird,
            "is_winner": usergame.is_winner, 
            "guesses": [{**b.info(), "correctness": b.compare(game.bird)} for b in bird_guesses],
            "guess_count": usergame.guess_count,
            "emojis": build_results_emojis(game, bird_guesses)
        }
        return render(request, 'birdle/daily_bird.html', context)
    
    elif request.method == "POST":
        # Check if they still have guesses and have not won already
        if usergame.guess_count < 6 and not usergame.is_winner:
            # Get the Bird the user guessed
            try:
                guess = Bird.objects.get(name=request.POST.get('guess-input'))
            except (KeyError, Bird.DoesNotExist):
                error_msg = "That bird doesn't exist!"
                return HttpResponse(error_msg, status=400)

            # Add the user's guess to the database
            Guess.objects.create(
                usergame=usergame,
                bird=guess
            )
        
        # Get all user guesses
        guesses = Guess.objects.filter(usergame=usergame)

        # Convert guesses to Birds
        bird_guesses = [guess.bird for guess in guesses]

        context = {
            "is_winner": usergame.is_winner,
            "new_guess": render_to_string("birdle/guess.html", {**guess.info(), "correctness": guess.compare(game.bird)}),
            "guess_count": guesses.count(),
            "emojis": build_results_emojis(game, bird_guesses)
        }
        return JsonResponse(context)


def stats(request):
    # Retrieve the user's guess history from the database
    user, _ = User.objects.get_or_create(username=request.session["username"])
    usergames = [game for game in UserGame.objects.filter(user=user) if game.guess_count > 0]
    
    games_played = len(usergames)
    wins = [game for game in usergames if game.is_winner]
    games_won = len(wins)
    win_pct = games_won/games_played if games_played > 0 else 0
    guess_counts = [game.guess_count for game in wins]
    guess_dist = [
        {"guesses": i, "count": guess_counts.count(i)} for i in range(1, 7)
    ]

    def result(result):
        return "Win" if result else "Loss"
    
    game_results = {
        str(usergame.game.date): result(usergame.is_winner) \
              for usergame in usergames
    }

    first_game = datetime(2024,1,1) # min([usergame.game.date for usergame in usergames])
    today = todays_game().date
    date_list = date_range(first_game, today, freq='D') \
        .map(lambda x: x.strftime("%Y-%m-%d"))

    results = [game_results.get(date, "Did not play") for date in date_list]
    birds = [game.bird.name for game in Game.objects.filter(date__gte=first_game, date__lte=today)]
    history = [
        {"Date": date, "Result": result, "Bird": bird} for date, result, bird in zip(date_list, results, birds)
    ]
    
    # Hide todays result if they're still playing and haven't won
    todays_result = list(filter(lambda x: x.game.date == today, usergames))
    if todays_result:
        history = history[0:-1] if todays_result[0].guess_count < 6 and not todays_result[0].is_winner else history

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
                    birdregions = birdregions.filter(region_name=decoded_region)
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

def get_bird_images(bird):
    images = Image.objects.filter(bird=bird)

    if images.count() > 2:
        return images
    else:
        response = requests.get(bird.url)
        soup = BeautifulSoup(response.content, "html.parser")
        items = soup.find_all("figure", class_="MediaFeed-item")[0:4] 
        labels = [x.find("h3").text or "Version " + str(i+1) for i, x in enumerate(items)]
        raw_photographer = [x.find("img")["alt"] for x in items]
        photographer = [p.replace(bird.name + " - ", "") for p in raw_photographer]
        urls = [x.find("img")["src"] for x in items]
        img_list = list(zip(labels, urls, photographer))

        range_req = requests.get(f"https://birdsoftheworld.org/bow/species/{bird.species_code}/cur/introduction")
        range_soup = BeautifulSoup(range_req.content, "html.parser")
        
        try:
            range_url = range_soup.find_all("figure", class_="Figure")[0].find("a")["data-asset-src"]
            img_list.append(("Range", range_url, None))
        except IndexError:
            HttpResponse("Range not found", status=400)
        
        imgs = []
        for (label, url, photographer) in img_list:
            img = Image.objects.create(url=url, label=label, photographer=photographer, bird=bird) 
            imgs.append(img)

        if len(imgs) <= 1:
            #TODO: Update game
            pass
        return imgs


def bird_autocomplete(request):
    query = request.GET.get('term', '')
    q = Q()
    for term in query.split(" "):
        q &= Q(name__icontains=term)

    # Search for birds with names containing the query
    birds = Bird.objects.filter(q).order_by("name")
    
    # Return a list of bird names as the autocomplete options
    options = [bird.name for bird in birds]

    return JsonResponse(options, safe=False)


def build_results_emojis(game, guesses, mode=None):
    answer = game.bird
    date = game.date.strftime("%Y-%m-%d")
    results = []
    n = len(guesses) if any([guess == answer for guess in guesses]) else "X"
    for guess in guesses:
        taxonomy = guess.compare(answer)
        row = "".join(["🐦" if i else "❌" for i in taxonomy]) # TODO: Add 🐤 if hard mode
        results.append(row)
    emojis = "\n".join(results)
    link = "https://www.play-birdle.com"
    return f"Birdle {date} {n}/6\n{emojis}\n{link}"


def error_404(request, exception):
    return render(request, '404.html', status=404)


def error_500(request):
    return render(request, '500.html', status=500)