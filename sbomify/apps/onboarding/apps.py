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
        """Import signal handlers and cron tasks when the app is ready."""
        from . import cron, signals

        _ = (signals, cron)
