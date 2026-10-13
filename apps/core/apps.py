from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = 'apps.core'
    verbose_name = 'Core — brands, outlets, smart pages, QR'

    def ready(self):
        # Imported here, not at module level: connecting signals needs the app
        # registry to be fully populated.
        from apps.core.signals import register_image_models

        register_image_models()
