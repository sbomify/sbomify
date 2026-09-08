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

        # Bound every Stripe request. The library defaults to 80 seconds, which
        # is longer than a page render can afford: workspace settings syncs the
        # subscription while rendering, on every tab and twice per tab, so an
        # unreachable Stripe took the whole section past the edge's own limit
        # and returned 504 instead of rendering from stored billing data.
        # The client keeps one requests session per thread, so a single shared
        # instance is safe here.
        # Compared rather than tested for truth: a negative timeout raises
        # inside requests and an infinite one is the unbounded wait again, so
        # neither may reach the client. Settings already screens the
        # environment; this keeps an override honest too.
        timeout = getattr(settings, "STRIPE_TIMEOUT_SECONDS", 0)
        if isinstance(timeout, int | float) and 0 < timeout < float("inf"):
            stripe.default_http_client = stripe.new_default_http_client(timeout=timeout)
