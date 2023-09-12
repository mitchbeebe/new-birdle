from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from birdle.models import Bird, Game, Guess, Image


@admin.register(Bird)
class BirdAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "url"]

@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ["id", "date", "bird"]
    ordering = ('date',)

@admin.register(Guess)
class GuessAdmin(admin.ModelAdmin):
    list_display = ["id", "game", "user", "bird"]

class UserAdmin(BaseUserAdmin):
    list_display = ["id", "username", "date_joined", "last_login"]

admin.site.unregister(User)
admin.site.register(User, UserAdmin)

@admin.register(Image)
class ImageAdmin(admin.ModelAdmin):
    list_display = ["id", "bird", "url"]