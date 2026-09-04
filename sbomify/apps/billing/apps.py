from __future__ import annotations

from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbomify.apps.billing"
    label = "billing"
    verbose_name = "Billing"

    def ready(self) -> None:
        # Import signals, tasks, and cron to register them with Django and Dramatiq.
        # Without importing cron here the `daily_stale_trial_check` actor is
        # never registered with the dramatiq worker.
        import stripe
        from django.conf import settings

        from . import cron, signals, tasks  # noqa: F401

        # Pin here rather than per call: every request the library makes then
        # states the version it was written against, so upgrading the library
        # cannot change request or response shapes underneath us.
        if getattr(settings, "STRIPE_API_VERSION", ""):
            stripe.api_version = settings.STRIPE_API_VERSION
