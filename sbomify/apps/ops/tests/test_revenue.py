"""MRR from plan list prices, including what it cannot price."""

from __future__ import annotations

from decimal import Decimal

import pytest

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.ops.services.revenue import recurring_revenue
from sbomify.apps.teams.models import Team


@pytest.fixture
def plans(db):
    BillingPlan.objects.create(key="community", name="Community")
    BillingPlan.objects.create(
        key="business",
        name="Business",
        monthly_price=Decimal("199.00"),
        annual_price=Decimal("1990.00"),
    )
    BillingPlan.objects.create(key="enterprise", name="Enterprise")


def _workspace(name: str, plan: str, **limits: object) -> Team:
    return Team.objects.create(
        name=name,
        billing_plan=plan,
        billing_plan_limits={"subscription_status": "active", **limits},
    )


@pytest.mark.django_db
class TestRecurringRevenue:
    def test_a_monthly_business_workspace_contributes_its_monthly_price(self, plans):
        _workspace("Monthly", "business", billing_period="monthly")

        revenue = recurring_revenue()

        assert revenue.mrr == Decimal("199.00")
        assert revenue.priced_workspaces == 1

    def test_an_annual_workspace_is_spread_over_the_year(self, plans):
        """Otherwise a year of annual customers reads as twelve spikes."""
        _workspace("Annual", "business", billing_period="annual")

        revenue = recurring_revenue()

        assert revenue.mrr == Decimal("165.83")
        assert revenue.arr == Decimal("1989.96")

    def test_a_community_workspace_contributes_nothing(self, plans):
        _workspace("Free", "community", billing_period="monthly")

        revenue = recurring_revenue()

        assert revenue.mrr == Decimal("0.00")
        assert revenue.priced_workspaces == 0
        assert revenue.unpriced_workspaces == 0

    def test_an_unpriced_enterprise_plan_is_reported_not_swallowed(self, plans):
        """A contract-priced customer must be visible, not a silent zero."""
        _workspace("Contract", "enterprise", billing_period="annual")

        revenue = recurring_revenue()

        assert revenue.mrr == Decimal("0.00")
        assert revenue.unpriced_workspaces == 1

    def test_a_workspace_with_no_billing_period_is_treated_as_monthly(self, plans):
        _workspace("Unspecified", "business")

        assert recurring_revenue().mrr == Decimal("199.00")
