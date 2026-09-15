from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.integrations"
    label = "integrations"

    def ready(self) -> None:
        """Register the dramatiq actors.

        Without this the scheduler queues ``periodic_integration_sync`` into a
        worker that has never heard of it, and the messages pile up
        undelivered.
        """
        from . import cron, tasks  # noqa: F401
