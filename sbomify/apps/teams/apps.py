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
        import sbomify.apps.teams.signals  # noqa: F401 - Import signals to register them
        import sbomify.apps.teams.signals.handlers  # noqa: F401
        import sbomify.apps.teams.tasks  # noqa: F401
