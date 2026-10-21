from django.apps import AppConfig


class WorkspacesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.teams"
    label = "teams"

    def ready(self) -> None:
        """Import notification providers when app is ready.

        Also imports tasks so their dramatiq actors (`verify_custom_domains`
        among them) are registered with the worker. Otherwise scheduler-queued
        messages would accumulate undelivered.
        """
        # handlers, not the package: importing sbomify.apps.teams.signals only
        # runs an empty __init__ and registers nothing. A signals.py used to sit
        # alongside this package, shadowed by it, and every receiver in it was
        # dead for as long as both existed.
        import sbomify.apps.teams.signals.handlers  # noqa: F401
        import sbomify.apps.teams.tasks  # noqa: F401
