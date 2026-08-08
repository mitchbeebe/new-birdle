from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .models import UserGame


@receiver(user_logged_in)
def merge_anonymous_history(sender, request, user, **kwargs):
    """Port an anonymous session's game history onto the account just logged into."""
    anon_username = request.session.get("username")
    if not anon_username or anon_username == user.username:
        return

    anon_user = User.objects.filter(username=anon_username, password="").first()
    if not anon_user or anon_user.pk == user.pk:
        return

    for usergame in UserGame.objects.filter(user=anon_user):
        if UserGame.objects.filter(user=user, game=usergame.game).exists():
            # User already has history for this game; drop the anonymous duplicate.
            usergame.delete()
        else:
            usergame.user = user
            usergame.save()

    anon_user.delete()
    request.session["username"] = user.username
