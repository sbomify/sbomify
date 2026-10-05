"""The guard that decides whether a workspace may move to a cheaper plan.

The guard used to count products and components only. Members is enforced the
same way (``max_users`` blocks an invite) and the comparison cards advertise it
as a quota, so a workspace could pick a plan with room for one person while
holding several, with an enabled button and no warning.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.services.plan_selection import build_plan_selection_context
from sbomify.apps.teams.models import Invitation, Member, Team

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


def _add_bot(workspace: Team) -> None:
    """A synthetic OIDC identity, provisioned the way the binding flow does.

    A pre_save guard reserves ``role="bot"`` for that flow and takes this flag
    as its opt-out, so this is the only way to write the row the guard protects.
    """
    user = User.objects.create(username=f"oidc-bot-{workspace.key}", email="bot@example.com")
    member = Member(user=user, team=workspace, role="bot")
    member._is_oidc_bot_provisioning = True
    member.save()


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


@pytest.mark.django_db
def test_a_pending_invitation_counts_against_the_target_cap(subscribed_workspace) -> None:
    """The invite path treats an unexpired invitation as a seat already taken,
    so a workspace one invitation over the cap must not be waved onto the plan."""
    _add_members(subscribed_workspace, 1)
    Invitation.objects.create(team=subscribed_workspace, email="ada@example.com", role="member")

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    limits = _community(context)
    assert limits["exceeds"] is True
    assert limits["resources"] == ["2 members (limit: 1)"]


@pytest.mark.django_db
def test_an_expired_invitation_holds_no_seat(subscribed_workspace) -> None:
    _add_members(subscribed_workspace, 1)
    Invitation.objects.create(
        team=subscribed_workspace,
        email="grace@example.com",
        role="member",
        expires_at=timezone.now() - timedelta(days=1),
    )

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    assert _community(context) == {"exceeds": False, "resources": []}


@pytest.mark.django_db
def test_a_bot_member_does_not_block_the_downgrade(subscribed_workspace) -> None:
    """Bot members are synthetic OIDC identities, not seats, and the invite path
    does not count them either."""
    _add_members(subscribed_workspace, 1)
    _add_bot(subscribed_workspace)

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    assert _community(context) == {"exceeds": False, "resources": []}


@pytest.mark.django_db
def test_the_usage_card_counts_people_not_seats(subscribed_workspace) -> None:
    """The usage card reports members the way the members tab does: a held seat
    is not a person, and a bot is not one either."""
    _add_members(subscribed_workspace, 2)
    Invitation.objects.create(team=subscribed_workspace, email="ada@example.com", role="member")
    _add_bot(subscribed_workspace)

    context = build_plan_selection_context(_request(), subscribed_workspace, {}).value

    assert context["usage"]["users"] == 2
