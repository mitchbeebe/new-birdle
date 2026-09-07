from django.apps import AppConfig


class BirdleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "birdle"

    def ready(self):
        from . import signals  # noqa: F401
