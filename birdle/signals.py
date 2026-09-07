from allauth.account.signals import user_logged_in
from django.contrib.auth.models import User
from django.db import transaction
from django.dispatch import receiver

from .models import UserGame


def is_anonymous_user(user):
    """Anonymous players are passwordless, emailless users with a numeric-timestamp username.

    ``get_or_create`` leaves ``password`` as an empty string, which Django still reports as
    "usable", so check for that explicitly.
    """
    passwordless = user.password == "" or not user.has_usable_password()
    return passwordless and user.email == "" and user.username.isdigit()


def merge_anonymous_history(request, user):
    """Move the session's anonymous game history onto ``user`` and drop the anonymous row."""
    anon_username = request.session.get("username")
    if anon_username and anon_username != user.username:
        try:
            anon_user = User.objects.get(username=anon_username)
        except User.DoesNotExist:
            anon_user = None
        if anon_user is not None and is_anonymous_user(anon_user):
            with transaction.atomic():
                for anon_usergame in UserGame.objects.filter(user=anon_user):
                    existing = UserGame.objects.filter(user=user, game=anon_usergame.game).first()
                    if existing is None:
                        anon_usergame.user = user
                        anon_usergame.save(update_fields=["user"])
                    elif anon_usergame.guess_count > existing.guess_count:
                        existing.delete()
                        anon_usergame.user = user
                        anon_usergame.save(update_fields=["user"])
                    else:
                        anon_usergame.delete()
                anon_user.delete()
    request.session["username"] = user.username


@receiver(user_logged_in)
def on_user_logged_in(request, user, **kwargs):
    merge_anonymous_history(request, user)
