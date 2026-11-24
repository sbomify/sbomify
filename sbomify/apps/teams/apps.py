from django.apps import AppConfig


class WorkspacesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.teams"
    label = "teams"

    def ready(self) -> None:
        """Import notification providers when app is ready.

        Also imports tasks and cron so their dramatiq actors
        (`verify_custom_domains`, `periodic_domain_verification`) are
        registered with the worker — otherwise scheduler-queued messages
        would accumulate undelivered.
        """
        import sbomify.apps.teams.cron  # noqa: F401

        # handlers, not the package: importing sbomify.apps.teams.signals only
        # runs an empty __init__ and registers nothing. A signals.py used to sit
        # alongside this package, shadowed by it, and every receiver in it was
        # dead for as long as both existed.
        import sbomify.apps.teams.signals.handlers  # noqa: F401
        import sbomify.apps.teams.tasks  # noqa: F401
