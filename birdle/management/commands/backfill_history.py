# backfill_history.py

import csv
from django.core.management.base import BaseCommand
from birdle.models import Bird, Game, User, UserGame, Guess


class Command(BaseCommand):
    help = 'Import historical games, users, usergames, and guesses from Birdle v1'

    def handle(self, *args, **options):
        CSV_FUNS = {
            "games-clean.csv": self.create_game,
            "users-clean.csv": self.create_user,
            "guesses-clean.csv": self.create_usergame_and_guess,
        }

        for file, func in CSV_FUNS.items():
            # Open the CSV file and create a CSV reader
            with open(f'birdle/static/birdle/historical-db/{file}') as csvfile:
                reader = csv.reader(csvfile)
                # Skip the header row
                next(reader)
                # Loop through each row in the CSV file 
                # and update or create the objects
                for row in reader:
                    func(row)

    def create_game(self, row):
        date, birdname = row

        bird = Bird.objects.get(name=birdname)

        game, _ = Game.objects.update_or_create(
            date=date,
            bird=bird
        )
        self.stdout.write(self.style.SUCCESS(f'Created game: {game}'))


    def create_user(self, row):
        user_id = row[0]

        user, _ = User.objects.update_or_create(
            username=user_id
        )
        self.stdout.write(self.style.SUCCESS(f'Created user: {user}'))


    def create_usergame_and_guess(self, row):
        date, user_id, birdname = row

        game = Game.objects.get(date=date)
        user = User.objects.get(username=user_id)
        bird = Bird.objects.get(name=birdname)

        usergame, _ = UserGame.objects.update_or_create(
            user=user,
            game=game
        )
        guess, _ = Guess.objects.update_or_create(
            usergame=usergame,
            bird=bird
        )
        self.stdout.write(self.style.SUCCESS(f'Created usergame and guess: {guess}'))