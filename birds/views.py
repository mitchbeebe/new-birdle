import random
import requests
from bs4 import BeautifulSoup
from django.shortcuts import render
from .models import Bird, Guess
from django.http import JsonResponse
import pytz
from datetime import datetime

spec = "norcar"
answer = Bird.objects.get(species_code=spec)
# answer = random.choice(Bird.objects.all())
response = requests.get(answer.url)
soup = BeautifulSoup(response.content, "html.parser")
items = soup.find_all("figure", class_="MediaFeed-item")[0:3]
imgs = {x.find("h3").text: x.find("img")["src"] for x in items}

def daily_bird(request):

    if request.method == "GET":
        # Get user_id if available
        user_id = request.session.get("user_id")
        # Get past guesses
        guesses = Guess.objects.filter(user_id=user_id) if user_id else []
        # Convert guesses to Birds
        bird_guesses = [Bird.objects.get(species_code=guess.species_code) for guess in guesses]
        # Check if any of past guesses were correct
        request.session['is_winner'] = any([guess == answer for guess in bird_guesses])
        # Set the current guess count
        request.session['guess_count'] = len(guesses)
        # Build the html for past guesses
        guesses_html = "".join([build_guess_html(guess, answer) for guess in bird_guesses])

        context = {
            "imgs": imgs, 
            "is_winner": request.session['is_winner'], 
            "emojis": build_results_emojis(bird_guesses, answer),
            "guesses_html": guesses_html, 
            "guess_count": request.session['guess_count']
        }
        return render(request, 'birds/daily_bird.html', context)
    
    elif request.method == "POST":
        # Check if they still have guesses and have not won already
        if request.session['guess_count'] < 6 and not request.session['is_winner']:
            # Get the user_id
            user_id = request.POST.get('user_id')
            request.session["user_id"] = user_id
            # Get the Bird the user guessed
            guess = Bird.objects.get(name=request.POST.get('guess-input'))
            # Build the html for their guess
            guess_html = build_guess_html(guess, answer)
            # Determine if the user won
            request.session['is_winner'] = request.session.get('is_winner') or guess == answer

            # Add the user's guess to the database
            Guess.objects.create(
                user_id=user_id,
                species_code=guess.species_code
            )
            # Increment their guess count
            request.session['guess_count'] += 1   
        else:
            guess_html = ""
        
        # Get all user guesses
        guesses = Guess.objects.filter(user_id=user_id)
        # Convert guesses to Birds
        bird_guesses = [Bird.objects.get(species_code=guess.species_code) for guess in guesses]
        
        context = {
            "is_winner": request.session['is_winner'],
            "emojis": build_results_emojis(bird_guesses, answer),
            "guesses_html": guess_html, 
            "answer": answer.taxonomy(),
            "guess_count": request.session['guess_count']
        }
        print(context)
        return JsonResponse(context)


def stats(request):
    # Retrieve the user's guess history from the database
    user_guesses = Guess.objects.filter(user_id=request.session['user_id'])
    birds = [Bird.objects.get(species_code=i.species_code) for i in user_guesses]
    guesses = [bird.name for bird in birds]
    # # Calculate additional statistics based on the guess history
    # total_games = user_guesses.count()
    # total_wins = user_guesses.filter(correct=True).count()
    # total_loss = total_games - total_wins
    # win_percentage = (total_wins / total_games) * 100
    # current_streak = 0
    # max_streak = 0
    # for guess in user_guesses:
    #     if guess.correct:
    #         current_streak += 1
    #         max_streak = max(max_streak, current_streak)
    #     else:
    #         current_streak = 0

    # # Count the frequency of guesses that were correct in 1-6 attempts
    # correct_guesses = [0] * 6
    # for guess in user_guesses:
    #     if guess.correct:
    #         num_attempts = guess.num_attempts
    #         if num_attempts <= 6:
    #             correct_guesses[num_attempts - 1] += 1

    # Render the guess history template with the data
    return render(request, 'birds/stats.html', {"guesses": guesses})

def info(request):
    return render(request, 'birds/info.html')


def bird_autocomplete(request):
    query = request.GET.get('term', '')

    # Search for birds with names containing the query
    birds = Bird.objects.filter(name__icontains=query)[:10]

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
    emojis = "\\n".join(results)
    link = "https://www.play-birdle.com"
    return f"Birdle #1 {n}/6\\n{emojis}\\n{link}"