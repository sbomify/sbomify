"""Who reads the members, invitations and billing in a workspace response.

The settings pages show members and billing to admins and owners only. The
workspace API answered every internal reader with all of it: each member's
email, each invitation's email and token, and the billing limits.
"""

from __future__ import annotations

import pytest
from django.test import Client

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Invitation, Member

pytestmark = pytest.mark.django_db


@pytest.fixture
def workspace(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    team.billing_plan_limits = {"stripe_customer_id": "cus_example", "stripe_subscription_id": "sub_example"}
    team.save(update_fields=["billing_plan_limits"])
    invitation = Invitation.objects.create(team=team, email="invitee@example.com", role="member")
    return team, invitation


def _reader(team, role: str, django_user_model) -> Client:
    user = django_user_model.objects.create_user(username=f"{role}-reader", email=f"{role}-reader@example.com")
    Member.objects.create(team=team, user=user, role=role)
    client = Client()
    setup_authenticated_client_session(client, team, user)
    return client


@pytest.mark.parametrize("role", ["member", "operator"])
@pytest.mark.parametrize("listing", [False, True])
def test_a_reader_below_admin_sees_only_their_own_details(role, listing, workspace, sample_user, django_user_model):
    team, invitation = workspace
    client = _reader(team, role, django_user_model)

    response = client.get("/api/v1/workspaces/" if listing else f"/api/v1/workspaces/{team.key}")

    assert response.status_code == 200
    body = response.content.decode()
    data = response.json()[0] if listing else response.json()
    assert f"{role}-reader@example.com" in body
    assert sample_user.email not in body
    assert invitation.email not in body
    assert str(invitation.token) not in body
    assert data["billing_plan_limits"] is None
    # The workspaces page counts both and finds the reader's own row.
    assert len(data["members"]) == 2
    assert len(data["invitations"]) == 1


def test_an_admin_still_reads_every_detail(workspace, sample_user, django_user_model):
    team, invitation = workspace
    client = _reader(team, "admin", django_user_model)

    body = client.get(f"/api/v1/workspaces/{team.key}").content.decode()

    assert sample_user.email in body
    assert invitation.email in body
    assert str(invitation.token) in body
    assert "cus_example" in body
