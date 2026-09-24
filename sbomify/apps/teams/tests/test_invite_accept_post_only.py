"""The invitation link opens a confirmation page; only its POST accepts."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.documents.access_models import AccessRequest
from sbomify.apps.teams.models import Invitation, Member, Team


@pytest.fixture
def invitee() -> Any:
    user = get_user_model().objects.create_user(username="invitee", email="invitee@example.com", password="pw")
    # A workspace of their own, so signing in leaves the invitation pending.
    home = Team.objects.create(name="Invitee Home")
    Member.objects.create(team=home, user=user, role="owner", is_default_team=True)
    return user


@pytest.fixture
def invitation(team_with_business_plan: Team, invitee: Any) -> Invitation:
    return Invitation.objects.create(team=team_with_business_plan, email=invitee.email, role="member")


def _url(token: object) -> str:
    return reverse("teams:accept_invite", kwargs={"invite_token": str(token)})


def _form_token(response: Any) -> str:
    match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode())
    assert match, "the confirmation form carries no CSRF token"
    return match.group(1)


@pytest.mark.django_db
def test_emailed_link_confirms_before_joining(invitee: Any, invitation: Invitation) -> None:
    client = Client(enforce_csrf_checks=True)
    url = _url(invitation.token)

    response = client.get(url)
    assert response.status_code == 302
    assert response.url == f"{reverse('core:keycloak_login')}?next={quote(url)}"

    client.force_login(invitee)
    response = client.get(url)

    assert response.status_code == 200
    body = response.content.decode()
    assert re.search(rf'<form[^>]*method="post"[^>]*action="{re.escape(url)}"', body)
    assert 'data-pending-invitations="1"' not in body, "the page repeats the settings toast"
    assert not Member.objects.filter(team=invitation.team, user=invitee).exists()
    assert Invitation.objects.filter(pk=invitation.pk).exists()

    response = client.post(url, {"csrfmiddlewaretoken": _form_token(response)})

    assert response.status_code == 302
    assert response.url == reverse("core:dashboard")
    assert Member.objects.filter(team=invitation.team, user=invitee, role="member").exists()
    assert not Invitation.objects.filter(pk=invitation.pk).exists()


@pytest.mark.django_db
def test_link_leaves_an_existing_role_alone(invitee: Any, invitation: Invitation) -> None:
    membership = Member.objects.create(team=invitation.team, user=invitee, role="guest")
    client = Client()
    client.force_login(invitee)

    response = client.get(_url(invitation.token))

    assert response.status_code == 200
    membership.refresh_from_db()
    assert membership.role == "guest"
    assert Invitation.objects.filter(pk=invitation.pk).exists()

    client.post(_url(invitation.token))

    membership.refresh_from_db()
    assert membership.role == "member"


@pytest.mark.django_db
def test_nda_workspace_opens_the_access_request_on_confirm(
    mocker: MockerFixture, invitee: Any, invitation: Invitation
) -> None:
    mocker.patch.object(Team, "get_company_nda_document", return_value=object())
    client = Client()
    client.force_login(invitee)

    response = client.get(_url(invitation.token))

    assert response.status_code == 200
    assert not AccessRequest.objects.filter(team=invitation.team, user=invitee).exists()

    response = client.post(_url(invitation.token))

    access_request = AccessRequest.objects.get(team=invitation.team, user=invitee)
    assert response.url == reverse(
        "documents:sign_nda", kwargs={"team_key": invitation.team.key, "request_id": access_request.id}
    )


@pytest.mark.django_db
def test_confirmation_without_the_form_token_is_refused(invitee: Any, invitation: Invitation) -> None:
    client = Client(enforce_csrf_checks=True)
    client.force_login(invitee)

    response = client.post(_url(invitation.token))

    assert response.status_code == 403
    assert not Member.objects.filter(team=invitation.team, user=invitee).exists()


@pytest.mark.django_db
def test_another_account_gets_no_confirmation(invitation: Invitation) -> None:
    stranger = get_user_model().objects.create_user(username="stranger", email="stranger@example.com", password="pw")
    client = Client()
    client.force_login(stranger)

    response = client.get(_url(invitation.token))

    assert response.status_code == 404
    assert invitation.team.display_name not in response.content.decode()
    assert client.post(_url(invitation.token)).status_code == 404
    assert not Member.objects.filter(team=invitation.team, user=stranger).exists()


@pytest.mark.django_db
def test_invitation_id_is_not_a_token(invitee: Any, invitation: Invitation) -> None:
    client = Client()
    client.force_login(invitee)

    assert client.get(_url(invitation.pk)).status_code == 404
    assert client.post(_url(invitation.pk)).status_code == 404
    assert not Member.objects.filter(team=invitation.team, user=invitee).exists()
    assert Invitation.objects.filter(pk=invitation.pk).exists()
