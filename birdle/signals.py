from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile, UserGame


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


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)
