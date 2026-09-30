"""The guard that decides whether a workspace may move to a cheaper plan.

The guard used to count products and components only. Members is enforced the
same way (``max_users`` blocks an invite) and the comparison cards advertise it
as a quota, so a workspace could pick a plan with room for one person while
holding several, with an enabled button and no warning.
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.services.plan_selection import build_plan_selection_context
from sbomify.apps.teams.models import Member, Team

User = get_user_model()


def _request() -> RequestFactory:
    request = RequestFactory().get("/")
    SessionMiddleware(lambda req: None).process_request(request)
    return request


@pytest.fixture
def plans(db) -> None:
    BillingPlan.objects.update_or_create(
        key="community",
        defaults={"name": "Community", "max_users": 1, "max_products": 1, "max_components": 5},
    )
    BillingPlan.objects.update_or_create(
        key="business",
        defaults={"name": "Business", "max_users": 10, "max_products": 10, "max_components": 100},
    )


@pytest.fixture
def subscribed_workspace(db, plans) -> Team:
    workspace = Team.objects.create(
        name="Downgrade test",
        key="dg-test",
        billing_plan="business",
        billing_plan_limits={
            "subscription_status": "active",
            "stripe_customer_id": "cus_x",
            "stripe_subscription_id": "sub_x",
        },
    )
    return workspace


def _add_members(workspace: Team, count: int) -> None:
    for index in range(count):
        user = User.objects.create(username=f"member-{index}-{workspace.key}", email=f"m{index}@example.com")
        Member.objects.create(user=user, team=workspace, role="member")


def _community(context: dict) -> dict:
    return context["plan_selection_data"]["downgradeLimits"]["community"]


@pytest.mark.django_db
def test_members_over_the_target_cap_block_the_downgrade(subscribed_workspace) -> None:
    _add_members(subscribed_workspace, 3)

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    limits = _community(context)
    assert limits["exceeds"] is True
    assert limits["resources"] == ["3 members (limit: 1)"]


@pytest.mark.django_db
def test_a_workspace_that_fits_the_target_plan_is_not_blocked(subscribed_workspace) -> None:
    _add_members(subscribed_workspace, 1)

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    assert _community(context) == {"exceeds": False, "resources": []}


@pytest.mark.django_db
def test_the_cheaper_plan_is_marked_as_a_downgrade(subscribed_workspace) -> None:
    _add_members(subscribed_workspace, 1)

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    by_key = {plan["key"]: plan for plan in context["plans"]}
    assert by_key["community"]["downgrade"] is True
    assert by_key["business"]["downgrade"] is False
    assert by_key["business"]["current"] is True


@pytest.mark.django_db
def test_an_unsubscribed_workspace_is_never_blocked(plans) -> None:
    workspace = Team.objects.create(name="Free", key="free-test", billing_plan="business", billing_plan_limits={})
    _add_members(workspace, 5)

    context = build_plan_selection_context(_request(), workspace, {}).value

    assert _community(context)["exceeds"] is False
