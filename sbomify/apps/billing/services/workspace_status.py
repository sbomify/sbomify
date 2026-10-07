"""Canonical billing-state predicates for workspaces.

``billing_plan_limits["subscription_status"]`` is not a payment signal on its
own. ``teams.utils._setup_community_plan`` writes ``"active"`` for every free
community workspace at creation, and ``billing.config.get_unlimited_plan_limits``
writes it for every workspace when billing is switched off. Counting that
status alone reports almost the whole install as paying customers, which is
what the admin dashboard did until this module existed.

Anything that needs to know whether a workspace pays us should call these
rather than filter on the JSON field directly, so two reports cannot disagree.
"""

from __future__ import annotations

from django.db.models import QuerySet

from sbomify.apps.teams.models import Team

PAID_PLANS: tuple[str, ...] = (Team.Plan.BUSINESS, Team.Plan.ENTERPRISE)
"""Plans that carry a price. Mirrors the test in ``team_pricing_service``."""


def paying_workspaces() -> QuerySet[Team]:
    """Workspaces on a paid plan with a live subscription.

    Community is excluded because it carries ``subscription_status="active"``
    from the moment it is created. Trials are excluded because they have not
    paid yet, and past-due workspaces because their last payment failed. Both
    of those are real states worth reporting, just not as revenue: see
    ``trialing_workspaces`` and ``past_due_workspaces``.
    """
    return Team.objects.filter(
        billing_plan__in=PAID_PLANS,
        billing_plan_limits__subscription_status="active",
    )


def trialing_workspaces() -> QuerySet[Team]:
    """Workspaces inside a free trial of a paid plan."""
    return Team.objects.filter(billing_plan_limits__subscription_status="trialing")


def past_due_workspaces() -> QuerySet[Team]:
    """Workspaces whose most recent payment failed and are in dunning."""
    return Team.objects.filter(billing_plan_limits__subscription_status="past_due")


def canceled_workspaces() -> QuerySet[Team]:
    """Workspaces whose subscription was canceled.

    Deliberately not filtered by plan: cancelling downgrades the workspace to
    community, so a canceled row usually sits on the community plan.
    """
    return Team.objects.filter(billing_plan_limits__subscription_status="canceled")
