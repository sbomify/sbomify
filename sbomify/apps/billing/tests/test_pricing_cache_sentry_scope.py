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
    """A live Sentry client whose events land in a list instead of the network."""
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
        sentry_sdk.init(dsn=None, default_integrations=False)


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
        # str(): the SDK holds the tag as the bool it was given and stringifies it
        # on serialisation, so this reads the same either side of that.
        assert str(event["tags"]["pricing_cache_stale"]) == "True"
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
        assert str(captured_events[0]["tags"]["pricing_cache_stale"]) == "False"
        assert "pricing_cache" not in captured_events[0].get("contexts", {})

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
