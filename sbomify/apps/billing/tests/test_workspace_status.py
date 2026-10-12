"""What counts as a paying workspace.

The admin dashboard reported every workspace whose ``billing_plan_limits``
carried ``subscription_status="active"`` as a paying customer. That status is
written onto every free community workspace by ``_setup_community_plan``, so
the count was closer to "workspaces that finished plan setup" than to revenue.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from sbomify.apps.billing.services.workspace_status import (
    canceled_workspaces,
    past_due_workspaces,
    paying_workspaces,
    trialing_workspaces,
)
from sbomify.apps.teams.models import Team


@pytest.mark.django_db
class TestPayingWorkspaces:
    def test_a_community_workspace_is_not_paying(self):
        """Built exactly as ``_setup_community_plan`` builds it."""
        Team.objects.create(
            name="Community",
            billing_plan="community",
            billing_plan_limits={
                "max_products": 1,
                "max_components": 5,
                "subscription_status": "active",
                "last_updated": timezone.now().isoformat(),
            },
        )

        assert paying_workspaces().count() == 0

    def test_a_business_workspace_with_a_live_subscription_is_paying(self):
        Team.objects.create(
            name="Customer",
            billing_plan="business",
            billing_plan_limits={
                "subscription_status": "active",
                "stripe_subscription_id": "sub_123",
                "stripe_customer_id": "cus_123",
            },
        )

        assert paying_workspaces().count() == 1

    def test_enterprise_counts_without_stripe_ids(self):
        """Enterprise is sales-led and may be billed on contract."""
        Team.objects.create(
            name="Contract",
            billing_plan="enterprise",
            billing_plan_limits={"subscription_status": "active"},
        )

        assert paying_workspaces().count() == 1

    def test_a_trial_is_not_yet_revenue(self):
        Team.objects.create(
            name="Trial",
            billing_plan="business",
            billing_plan_limits={"subscription_status": "trialing"},
        )

        assert paying_workspaces().count() == 0
        assert trialing_workspaces().count() == 1

    def test_a_failing_payment_is_counted_separately(self):
        Team.objects.create(
            name="Dunning",
            billing_plan="business",
            billing_plan_limits={"subscription_status": "past_due"},
        )

        assert paying_workspaces().count() == 0
        assert past_due_workspaces().count() == 1

    def test_a_cancelled_workspace_is_found_on_the_community_plan(self):
        """Cancelling downgrades the plan, so canceled must not be plan-filtered."""
        Team.objects.create(
            name="Left",
            billing_plan="community",
            billing_plan_limits={"subscription_status": "canceled"},
        )

        assert canceled_workspaces().count() == 1
        assert paying_workspaces().count() == 0

    def test_a_workspace_with_no_limits_at_all_is_not_paying(self):
        Team.objects.create(name="Bare", billing_plan="community", billing_plan_limits=None)

        assert paying_workspaces().count() == 0
