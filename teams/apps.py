from django.apps import AppConfig


class TeamsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "teams"

    def ready(self):
        """Import notification providers when app is ready"""
        import teams.signals.handlers  # noqa: F401
