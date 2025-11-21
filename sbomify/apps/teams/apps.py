from django.apps import AppConfig


class WorkspacesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.teams"
    label = "teams"

    def ready(self):
        """Import notification providers when app is ready"""
        import sbomify.apps.teams.signals.handlers  # noqa: F401
