from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.core"
    label = "core"

    def ready(self):
        # Import signals to register them
        import sbomify.apps.core.signals  # noqa: F401
