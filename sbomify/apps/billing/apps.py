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
        from . import cron, signals, tasks  # noqa: F401
