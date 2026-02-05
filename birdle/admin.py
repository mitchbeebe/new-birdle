from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from django.urls import reverse
from birdle.models import Bird, Game, Guess, Image, UserGame, BirdRegion, Region


def linkify(field_name):
    """
    Converts a foreign key value into clickable links.

    If field_name is 'parent', link text will be str(obj.parent)
    Link will be admin url for the admin url for obj.parent.id:change
    """

    def _linkify(obj):
        linked_obj = getattr(obj, field_name)
        if linked_obj is None:
            return "-"
        app_label = linked_obj._meta.app_label
        model_name = linked_obj._meta.model_name
        view_name = f"admin:{app_label}_{model_name}_change"
        link_url = reverse(view_name, args=[linked_obj.pk])
        return format_html('<a href="{}">{}</a>', link_url, linked_obj)

    setattr(_linkify, "short_description", field_name)  # Sets column name
    return _linkify


@admin.register(Bird)
class BirdAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "url"]
    search_fields = ["name"]


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ["id", "date", "region", linkify("bird"), "img_count"]
    search_fields = ["date", "bird__name"]
    ordering = ("date",)
    list_filter = ("date",)


@admin.register(Guess)
class GuessAdmin(admin.ModelAdmin):
    list_display = ["id", "bird"]


class UserAdmin(BaseUserAdmin):
    list_display = ["id", "username", "date_joined", "last_login"]


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(Image)
class ImageAdmin(admin.ModelAdmin):
    list_display = ["id", "bird", "url"]


@admin.register(UserGame)
class UserGameAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "game", "guess_count", "is_winner"]


@admin.register(BirdRegion)
class BirdRegionAdmin(admin.ModelAdmin):
    list_display = ["id", "bird", "region"]
    search_fields = ["bird__name", "region__name"]


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "code"]
