"""What the access-request queue answers after each action.

An htmx post gets the refreshed queue section and a trigger. Any other post
lands on the trust-center tab, told to refresh, when it came from there, and on
the queue otherwise.
"""

import pytest
from django.core.cache import cache
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.documents.access_models import AccessRequest
from sbomify.apps.teams.models import Invitation

pytestmark = pytest.mark.django_db


@pytest.fixture
def queue(authenticated_web_client, team_with_business_plan, sample_user):
    setup_authenticated_client_session(authenticated_web_client, team_with_business_plan, sample_user)
    return authenticated_web_client, reverse(
        "documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key}
    )


def _assert_lands_back(response, team, active_tab):
    assert response.status_code == 302
    if active_tab:
        assert response.url == reverse("teams:team_settings", kwargs={"team_key": team.key}) + "#trust-center"
        assert response["HX-Trigger"] == "refreshAccessRequests"
    else:
        assert response.url == reverse("documents:access_request_queue", kwargs={"team_key": team.key})
        assert "HX-Trigger" not in response


def test_an_htmx_decision_returns_the_refreshed_queue(queue, team_with_business_plan, guest_user):
    client, url = queue
    access_request = AccessRequest.objects.create(team=team_with_business_plan, user=guest_user)

    response = client.post(url, {"action": "approve", "request_id": access_request.id}, HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert response["HX-Trigger"] == "refreshAccessRequests"
    body = response.content.decode()
    assert "Approved Requests" in body
    assert guest_user.email in body


def test_an_htmx_invite_returns_the_queue_and_closes_the_modal(queue, sample_user):
    client, url = queue

    response = client.post(url, {"action": "invite", "email": "invitee@example.com"}, HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert response["HX-Trigger"] == "refreshAccessRequests,closeInviteModal"
    body = response.content.decode()
    assert "invitee@example.com" in body
    assert sample_user.email in body


def test_an_htmx_cancellation_returns_the_queue_without_the_invitation(queue, team_with_business_plan, sample_user):
    client, url = queue
    invitation = Invitation.objects.create(team=team_with_business_plan, email="invitee@example.com", role="guest")
    cache.set(f"invitation_inviter:{invitation.token}", sample_user.id)

    response = client.post(url, {"action": "cancel_invitation", "invitation_id": invitation.id}, HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert response["HX-Trigger"] == "refreshAccessRequests"
    assert "invitee@example.com" not in response.content.decode()
    assert not Invitation.objects.filter(pk=invitation.pk).exists()
    assert cache.get(f"invitation_inviter:{invitation.token}") is None


@pytest.mark.parametrize("active_tab", ["trust-center", ""])
def test_a_cancellation_lands_back_where_it_came_from(queue, team_with_business_plan, active_tab):
    client, url = queue
    invitation = Invitation.objects.create(team=team_with_business_plan, email="invitee@example.com", role="guest")

    response = client.post(
        url, {"action": "cancel_invitation", "invitation_id": invitation.id, "active_tab": active_tab}
    )

    _assert_lands_back(response, team_with_business_plan, active_tab)
    assert not Invitation.objects.filter(pk=invitation.pk).exists()


@pytest.mark.parametrize("active_tab", ["trust-center", ""])
@pytest.mark.parametrize(
    "refusal",
    [
        "cancellation without an invitation",
        "cancellation of an unknown invitation",
        "invite without an email",
        "invite of a member",
        "invite of an address already invited",
        "no action",
        "unknown request",
        "approving a decided request",
        "revoking a pending request",
        "clearing a pending request",
        "unknown action",
    ],
)
def test_a_refused_action_lands_back_where_it_came_from(
    queue, team_with_business_plan, sample_user, guest_user, refusal, active_tab
):
    client, url = queue
    pending = AccessRequest.objects.create(team=team_with_business_plan, user=guest_user)
    Invitation.objects.create(team=team_with_business_plan, email="invited@example.com", role="guest")
    data = {
        "cancellation without an invitation": {"action": "cancel_invitation"},
        "cancellation of an unknown invitation": {"action": "cancel_invitation", "invitation_id": "999999"},
        "invite without an email": {"action": "invite"},
        "invite of a member": {"action": "invite", "email": sample_user.email},
        "invite of an address already invited": {"action": "invite", "email": "invited@example.com"},
        "no action": {},
        "unknown request": {"action": "approve", "request_id": "missing"},
        "approving a decided request": {"action": "reject", "request_id": pending.id},
        "revoking a pending request": {"action": "revoke", "request_id": pending.id},
        "clearing a pending request": {"action": "clear_rejection", "request_id": pending.id},
        "unknown action": {"action": "promote", "request_id": pending.id},
    }[refusal]
    if refusal == "approving a decided request":
        client.post(url, data)
        data = {"action": "approve", "request_id": pending.id}

    response = client.post(url, {**data, "active_tab": active_tab})

    _assert_lands_back(response, team_with_business_plan, active_tab)


def test_the_queue_names_the_inviter_from_the_invited_accounts_request(
    queue, team_with_business_plan, sample_user, guest_user
):
    """With the cache entry gone, the inviter comes from the decided_by on the invitee's request."""
    client, url = queue
    Invitation.objects.create(team=team_with_business_plan, email=guest_user.email, role="guest")
    AccessRequest.objects.create(team=team_with_business_plan, user=guest_user, decided_by=sample_user)

    response = client.get(url, HTTP_HX_REQUEST="true")

    assert response.status_code == 200
    assert sample_user.email in response.content.decode().split("Pending invitations", 1)[1]
