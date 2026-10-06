from django.apps import AppConfig


class KidsplayConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.kidsplay"
    label = "kidsplay"
    verbose_name = "KidsPlay"

    def ready(self):
        from apps.kidsplay import signals  # noqa: F401
