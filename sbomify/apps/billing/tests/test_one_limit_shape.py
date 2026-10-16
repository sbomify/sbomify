"""Products, components and seats are limited through one map and one count."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from sbomify.apps.billing.billing_processing import get_resource_limit
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.queries import get_team_asset_count
from sbomify.apps.teams.models import Invitation, Member, Workspace
from sbomify.apps.teams.utils import can_add_user_to_team

User = get_user_model()


@pytest.fixture
def team_with_three_seats(db):
    BillingPlan.objects.create(key="business", name="Business", max_users=3, max_products=5, max_components=7)
    team = Workspace.objects.create(name="Seats", billing_plan="business")
    owner = User.objects.create_user(username="seat-owner", email="seat-owner@example.com")
    Member.objects.create(user=owner, team=team, role="owner")
    return team


def _invite(team, email, *, expired=False):
    invitation = Invitation.objects.create(team=team, email=email, role="member")
    if expired:
        Invitation.objects.filter(pk=invitation.pk).update(expires_at=timezone.now() - timedelta(days=1))
    return invitation


@pytest.mark.django_db
def test_every_resource_reads_its_limit_from_the_one_map(team_with_three_seats):
    plan = BillingPlan.objects.get(key="business")
    assert get_resource_limit(plan, "product") == 5
    assert get_resource_limit(plan, "component") == 7
    assert get_resource_limit(plan, "user") == 3


@pytest.mark.django_db
def test_a_seat_is_a_member_or_an_unexpired_invitation(team_with_three_seats):
    team = team_with_three_seats
    bot = Member(user=User.objects.create_user(username="seat-bot"), team=team, role="bot")
    bot._is_oidc_bot_provisioning = True
    bot.save()
    _invite(team, "pending@example.com")
    _invite(team, "lapsed@example.com", expired=True)

    assert get_team_asset_count(str(team.id), "user") == 2


@pytest.mark.django_db
def test_a_new_seat_is_refused_once_every_seat_is_taken(team_with_three_seats):
    team = team_with_three_seats
    _invite(team, "one@example.com")
    _invite(team, "two@example.com")

    can_add, message = can_add_user_to_team(team)

    assert can_add is False
    assert message == "Your Business plan allows only 3 users. Please upgrade your plan to add more members."


@pytest.mark.django_db
def test_an_invitee_joins_into_the_seat_their_invitation_holds(team_with_three_seats):
    team = team_with_three_seats
    _invite(team, "one@example.com")
    _invite(team, "two@example.com")

    assert can_add_user_to_team(team, is_joining_via_invite=True) == (True, "")


@pytest.mark.django_db
def test_an_expired_invitation_holds_no_seat(team_with_three_seats):
    team = team_with_three_seats
    _invite(team, "one@example.com")
    _invite(team, "lapsed@example.com", expired=True)

    assert can_add_user_to_team(team) == (True, "")


@pytest.mark.django_db
def test_seats_are_counted_by_the_shared_count(team_with_three_seats, mocker):
    counted = mocker.patch("sbomify.apps.teams.utils.get_team_asset_count", return_value=3)

    can_add, _message = can_add_user_to_team(team_with_three_seats)

    assert can_add is False
    counted.assert_called_with(str(team_with_three_seats.id), "user")
