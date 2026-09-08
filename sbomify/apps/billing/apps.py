from __future__ import annotations

from django.apps import AppConfig


def usable_timeout(value: object) -> float | None:
    """``value`` as a timeout in seconds, or None when it cannot be one.

    Rejects bool before number, because bool is a subclass of int and ``True``
    would otherwise install a one second timeout without saying so. Rejects
    anything not positive and finite as well: requests raises on a negative
    timeout, and an infinite one is the unbounded wait the caller is trying to
    remove.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    # NaN fails every comparison, so this rejects it too.
    if not (0 < value < float("inf")):
        return None
    return float(value)


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
        # Screened rather than trusted: settings already filters the
        # environment, but STRIPE_TIMEOUT_SECONDS can also be set directly by
        # another settings module, and a value that is not a positive finite
        # number must not reach the client.
        timeout = usable_timeout(getattr(settings, "STRIPE_TIMEOUT_SECONDS", None))
        if timeout is not None:
            stripe.default_http_client = stripe.new_default_http_client(timeout=timeout)
