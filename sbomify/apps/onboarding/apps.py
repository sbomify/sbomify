"""
Onboarding app configuration.
"""

from django.apps import AppConfig


class OnboardingConfig(AppConfig):
    """Configuration for the onboarding app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.onboarding"
    verbose_name = "Onboarding"

    def ready(self) -> None:
        """Import signal handlers and tasks when the app is ready.

        The worker registers the actors in tasks/__init__.py only through this
        import, because rundramatiq hands a tasks package's submodules to the
        worker processes, not the package itself.
        """
        from . import signals, tasks

        _ = (signals, tasks)
