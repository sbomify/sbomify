from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)

# Used when the configured value cannot be a timeout. Falling back to the
# library's own default instead would be an 80 second wait, which is the wait
# this whole mechanism exists to remove.
DEFAULT_STRIPE_TIMEOUT_SECONDS = 10.0


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


def install_bounded_http_client(configured: object) -> float:
    """Give Stripe an HTTP client that cannot wait forever, and say how long.

    Always installs one. Skipping the install when the configured value is
    unusable would leave the library's own 80 second default in place, which
    is the unbounded wait this exists to remove, and it would do so silently.
    Settings already screens the environment, so reaching the fallback means
    another settings module set the value directly.

    The client keeps one requests session per thread, so a single shared
    instance is safe under concurrent requests.
    """
    import stripe

    timeout = usable_timeout(configured)
    if timeout is None:
        logger.warning(
            "STRIPE_TIMEOUT_SECONDS is not a positive finite number (%r); using %s seconds instead.",
            configured,
            DEFAULT_STRIPE_TIMEOUT_SECONDS,
        )
        timeout = DEFAULT_STRIPE_TIMEOUT_SECONDS
    stripe.default_http_client = stripe.new_default_http_client(timeout=timeout)
    return timeout


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
        install_bounded_http_client(getattr(settings, "STRIPE_TIMEOUT_SECONDS", None))
