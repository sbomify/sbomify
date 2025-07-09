from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        # Import signals to register them
        import core.signals  # noqa: F401

        # Connect m2m signals after all models are loaded
        core.signals.connect_m2m_signals()
