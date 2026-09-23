"""The stale-cache signal has to arrive on the Stripe client's own event.

The rest of the pricing tests assert against a mocked ``sentry_sdk``, which
proves the service asks for the tag but not that an event picks it up. This
file drives the real SDK through a capturing transport, because the whole point
of scoping the Stripe call is that the error the client raises carries the
staleness rather than a second issue arriving to report it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import sentry_sdk
from django.utils import timezone
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.types import Event

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_pricing_service import StripePricingService


@pytest.fixture
def captured_events() -> Iterator[list[Event]]:
    """A live Sentry client whose events land in a list instead of the network.

    ``sentry_sdk.init`` replaces the global scope's client, so the original has
    to be put back rather than replaced with a bare one: every later test in
    the same worker would otherwise run without the integrations ``settings.py``
    wired up. Same requirement, and the same remedy, as the
    ``sentry_client_isolation`` fixture in ``sbomify/apps/core/tests/test_sentry_config.py``
    — only the global scope is restored, because setting a client on the current
    or isolation scope pins it there and breaks the SDK's scope fallback chain.
    """
    original = sentry_sdk.Scope.get_global_scope().client
    events: list[Event] = []
    sentry_sdk.init(
        dsn="https://public@example.ingest.sentry.io/1",
        transport=events.append,
        # Only the logging integration: the point here is the ERROR-level line
        # the Stripe client writes, which is what becomes an issue in production.
        integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
        default_integrations=False,
    )
    try:
        yield events
    finally:
        sentry_sdk.Scope.get_global_scope().set_client(original)


def _log_then_raise(*_args: Any, **_kwargs: Any) -> None:
    """Stand in for a post-fetch failure that reports to Sentry on its own."""
    logging.getLogger("sbomify.apps.billing.save").error("could not persist refreshed pricing")
    raise RuntimeError("save failed")


@pytest.mark.django_db
class TestStaleCacheRidesOnTheStripeEvent:
    @pytest.fixture
    def mock_stripe_client(self) -> Iterator[MagicMock]:
        client = MagicMock()
        with patch("sbomify.apps.billing.stripe_pricing_service.get_stripe_client", return_value=client):
            yield client

    @staticmethod
    def _fail_the_refresh(client: MagicMock) -> None:
        """Fail the way the real client does: log at error, then raise."""
        from sbomify.apps.billing.stripe_client import StripeError

        def boom(*_args: Any, **_kwargs: Any) -> None:
            logging.getLogger("sbomify.apps.billing.stripe_client").error("Stripe API connection error")
            raise StripeError("Could not connect to payment provider.")

        client.get_all_products_with_prices.side_effect = boom

    def test_the_client_event_carries_the_staleness(
        self, mock_stripe_client: MagicMock, captured_events: list[Event], db: None
    ) -> None:
        import datetime

        BillingPlan.objects.create(key="community", name="Community", description="Community")
        BillingPlan.objects.create(
            key="business",
            name="Business",
            description="Business",
            stripe_product_id="prod_business",
            monthly_price=Decimal("199.00"),
            last_synced_at=timezone.now() - datetime.timedelta(hours=25),
        )
        self._fail_the_refresh(mock_stripe_client)

        StripePricingService().get_all_plans_pricing(force_refresh=True)

        assert len(captured_events) == 1, "one failed refresh must not produce two issues"
        event = captured_events[0]
        assert event["logentry"]["message"] == "Stripe API connection error"
        # Lowercase, and asserted exactly: this is the literal an operator's
        # alert rule matches on, and Sentry compares tags as strings.
        assert event["tags"]["pricing_cache_stale"] == "true"
        assert event["contexts"]["pricing_cache"]["stale_plans"] == ["business"]

    def test_a_fresh_cache_says_so_on_the_same_event(
        self, mock_stripe_client: MagicMock, captured_events: list[Event], db: None
    ) -> None:
        import datetime

        BillingPlan.objects.create(key="community", name="Community", description="Community")
        BillingPlan.objects.create(
            key="business",
            name="Business",
            description="Business",
            stripe_product_id="prod_business",
            monthly_price=Decimal("199.00"),
            last_synced_at=timezone.now() - datetime.timedelta(minutes=5),
        )
        self._fail_the_refresh(mock_stripe_client)

        StripePricingService().get_all_plans_pricing(force_refresh=True)

        assert len(captured_events) == 1
        assert captured_events[0]["tags"]["pricing_cache_stale"] == "false"
        assert "pricing_cache" not in captured_events[0].get("contexts", {})

    def test_a_failure_saving_the_result_does_not_inherit_the_tag(
        self, mock_stripe_client: MagicMock, captured_events: list[Event], db: None
    ) -> None:
        """The scope covers the Stripe call, not the database work after it.

        Stripe answering and the save then failing is a different fault. Tagging
        it ``pricing_cache_stale`` would put it in front of whoever is looking
        for Stripe outages, describing a cache that the successful call just
        refreshed anyway.
        """
        import datetime

        BillingPlan.objects.create(key="community", name="Community", description="Community")
        BillingPlan.objects.create(
            key="business",
            name="Business",
            description="Business",
            stripe_product_id="prod_business",
            monthly_price=Decimal("199.00"),
            last_synced_at=timezone.now() - datetime.timedelta(hours=25),
        )
        mock_stripe_client.get_all_products_with_prices.return_value = []

        service = StripePricingService()
        with patch.object(service, "_process_stripe_data", side_effect=_log_then_raise):
            with pytest.raises(RuntimeError):
                service.get_all_plans_pricing(force_refresh=True)

        assert len(captured_events) == 1
        assert "pricing_cache_stale" not in (captured_events[0].get("tags") or {})
        assert "pricing_cache" not in (captured_events[0].get("contexts") or {})

    def test_the_tag_does_not_leak_past_the_stripe_call(
        self, mock_stripe_client: MagicMock, captured_events: list[Event], db: None
    ) -> None:
        """The scope wraps one call; a later unrelated error must not inherit it."""
        import datetime

        BillingPlan.objects.create(key="community", name="Community", description="Community")
        BillingPlan.objects.create(
            key="business",
            name="Business",
            description="Business",
            stripe_product_id="prod_business",
            monthly_price=Decimal("199.00"),
            last_synced_at=timezone.now() - datetime.timedelta(hours=25),
        )
        self._fail_the_refresh(mock_stripe_client)

        StripePricingService().get_all_plans_pricing(force_refresh=True)
        logging.getLogger("sbomify.apps.billing.elsewhere").error("something else entirely")

        assert len(captured_events) == 2
        assert "pricing_cache_stale" not in (captured_events[1].get("tags") or {})
