import json
import requests
from bs4 import BeautifulSoup
from django.shortcuts import redirect, render
from urllib.parse import quote, unquote
from .models import Bird, Guess, User, Game, Image
from .forms import FlashcardForm
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
import pytz
from datetime import date
from random import choices


def todays_game():
    today = date.today()
    game = Game.objects.get(date=today)
    return game


def daily_bird(request):
    game = todays_game()
    if request.method == "GET":
        imgs = get_bird_images(game.bird)

        # Get user if available
        user, created = User.objects.get_or_create(id=request.user.id)
        # Get past guesses
        guesses = Guess.objects.filter(user=user, game=game)
        # Convert guesses to Birds
        bird_guesses = [guess.bird for guess in guesses]
        # Check if any of past guesses were correct
        request.session['is_winner'] = any([guess == game.bird for guess in bird_guesses])
        # Set the current guess count
        request.session['guess_count'] = len(guesses)
        # Build the html for past guesses
        guesses_html = "".join([build_guess_html(guess, game.bird) for guess in bird_guesses])

        context = {
            "imgs": imgs,
            "is_winner": request.session['is_winner'], 
            "emojis": build_results_emojis(bird_guesses, game.bird),
            "guesses_html": guesses_html, 
            "guess_count": request.session['guess_count']
        }
        return render(request, 'birdle/daily_bird.html', context)
    
    elif request.method == "POST":
        # Get the user
        user, created = User.objects.get_or_create(id=request.user.id)
        # Check if they still have guesses and have not won already
        if request.session['guess_count'] < 6 and not request.session['is_winner']:
            # Get the Bird the user guessed
            try:
                guess = Bird.objects.get(name=request.POST.get('guess-input'))
            except (KeyError, Bird.DoesNotExist):
                error_msg = "That bird doesn't exist!"
                return HttpResponse(error_msg, status=400)
            # Build the html for their guess
            guess_html = build_guess_html(guess, game.bird)
            # Determine if the user won
            request.session['is_winner'] = request.session.get('is_winner') or guess == game.bird

            # Add the user's guess to the database
            Guess.objects.create(
                user=user,
                game=game,
                bird=guess
            )
            # Increment their guess count
            request.session['guess_count'] += 1   
        else:
            guess_html = ""
        
        # Get all user guesses
        guesses = Guess.objects.filter(user=user)
        # Convert guesses to Birds
        bird_guesses = [guess.bird for guess in guesses]
        
        context = {
            "is_winner": request.session['is_winner'],
            "emojis": build_results_emojis(bird_guesses, game.bird),
            "guesses_html": guess_html, 
            "answer": game.bird.taxonomy(),
            "guess_count": request.session['guess_count']
        }
        return JsonResponse(context)


def stats(request):
    # Retrieve the user's guess history from the database
    user, created = User.objects.get_or_create(id=request.user.id)
    user_guesses = Guess.objects.filter(user=user)
    games_played = user_guesses.values_list("game").distinct().count()
    games_won = 1
    guess_freq = [
        {"guesses": 1, "count": 3},
        {"guesses": 2, "count": 5},
        {"guesses": 3, "count": 7},
        {"guesses": 4, "count": 8},
        {"guesses": 5, "count": 8},
        {"guesses": 6, "count": 4}
    ]
    current_streak = 1
    best_streak = 1

    # for guess in user_guesses:
    #     if guess.correct:
    #         current_streak += 1
    #         max_streak = max(max_streak, current_streak)
    #     else:
    #         current_streak = 0

    # Count the frequency of guesses that were correct in 1-6 attempts
    # correct_guesses = [0] * 6
    # for guess in user_guesses:
    #     if guess.correct:
    #         num_attempts = guess.num_attempts
    #         if num_attempts <= 6:
    #             correct_guesses[num_attempts - 1] += 1

    stats = {
        "games_played": games_played,
        "games_won": games_won,
        "win_pct": games_played/games_won,
        "guess_freq": json.dumps(guess_freq),
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
        family = kwargs.get("family")

        if family:
            decoded_family = unquote(family)
            if family == "Any":
                birds = choices(Bird.objects.all(), k=4)
            else:
                birds = choices(Bird.objects.filter(family=decoded_family), k=4)
                print(birds)
            bird = choices(birds, k=1)[0]
            options = list(set([bird.name for bird in birds]))
            data.update({
                "imgs": get_bird_images(bird=bird),
                "options": options,
                "answer": bird.name
            })
            print(data["answer"])
            form = FlashcardForm(initial={"family": decoded_family})
        else:
            form = FlashcardForm()
        return render(request, "birdle/practice.html", {"form": form, **data})
    elif request.method == "POST":
        form = FlashcardForm(request.POST)
        if form.is_valid():
            family = form.cleaned_data["family"]
            encoded_family = quote(family)
            return redirect("practice-family", family=encoded_family)


def get_bird_images(bird):
    images = Image.objects.filter(bird=bird)

    if images.count() > 0:
        imgs = [(image.label, image.url) for image in images]
    else:
        response = requests.get(bird.url)
        soup = BeautifulSoup(response.content, "html.parser")
        items = soup.find_all("figure", class_="MediaFeed-item")[0:4] 
        labels = [x.find("h3").text or "Version " + str(i+1) for i, x in enumerate(items)]
        urls = [x.find("img")["src"] for x in items]
        imgs = list(zip(labels, urls))

        range_req = requests.get(f"https://birdsoftheworld.org/bow/species/{bird.species_code}/cur/introduction")
        range_soup = BeautifulSoup(range_req.content, "html.parser")
        range_url = range_soup.find_all("figure", class_="Figure")[0].find("a")["href"]
        imgs.append(("Distribution", range_url))

        for label, url in imgs:
            Image.objects.create(url=url, label=label, bird=bird) 

    return imgs


def bird_autocomplete(request):
    query = request.GET.get('term', '')
    q = Q()
    for term in query.split(" "):
        q &= Q(name__icontains=term)

    # Search for birds with names containing the query
    birds = Bird.objects.filter(q)[:10]
    
    # Return a list of bird names as the autocomplete options
    options = [bird.name for bird in birds]

    return JsonResponse(options, safe=False)


def build_guess_html(guess, answer):
    guess_html = ""

    correctness = guess.compare(answer)
    # construct the taxonomy divs
    taxonomy = guess.taxonomy()
    order_div = f'<div class="col-sm taxonomy guess text-center {correctness[0]}">{taxonomy["order"]}</div>'
    family_div = f'<div class="col-sm taxonomy guess text-center {correctness[1]}">{taxonomy["family"]}</div>'
    genus_div = f'<div class="col-sm taxonomy guess text-center {correctness[2]}">{taxonomy["genus"]}</div>'
    species_div = f'<div class="col-sm taxonomy guess text-center {correctness[3]}">{taxonomy["name"]}</div>'

    # combine the divs into a single HTML string
    guess_html += f'<div class="row flex-nowrap">{order_div}{family_div}{genus_div}{species_div}</div>'
    return guess_html


def build_results_emojis(guesses, answer):
    results = []
    n = ""
    for guess in guesses:
        taxonomy = guess.compare(answer)
        n = len(guesses) if guess == answer else n
        row = "".join(["🐦" if i else "❌" for i in taxonomy])
        results.append(row)
    emojis = "\n".join(results)
    link = "https://www.play-birdle.com"
    return f"Birdle #1 {n}/6\n{emojis}\n{link}"


def error_404(request, exception):
    return render(request, '404.html', status=404)


def error_500(request):
    return render(request, '500.html', status=500)