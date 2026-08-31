"""Being invited to a workspace has to be visible somewhere.

Two paths, and both were silent. An existing member gets a bell notification
from the pending invitation, but it linked to whichever workspace happened to
be active rather than the page that accepts it. A brand-new user never sees
that notification at all: login auto-accepts and deletes the invitation, so
there is nothing left to notify about, and the only place that said so was the
accept-invite view a direct signup never reaches.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.core.models import User
from sbomify.apps.teams.models import Invitation, Member, Team
from sbomify.apps.teams.notifications import get_notifications
from sbomify.apps.teams.signals.handlers import _accept_pending_invitations


@pytest.fixture
def invited_user() -> User:
    return User.objects.create_user(username="invitee", email="invitee@example.test", password="pw")  # nosec B106


@pytest.fixture
def inviting_team() -> Team:
    return Team.objects.create(name="Lithium Labs")


def _invite(team: Team, email: str, role: str = "member") -> Invitation:
    return Invitation.objects.create(
        team=team,
        email=email,
        role=role,
        token=uuid.uuid4(),
        expires_at=timezone.now() + timedelta(days=7),
    )


@pytest.mark.django_db
def test_a_pending_invitation_raises_a_notification(invited_user: User, inviting_team: Team) -> None:
    _invite(inviting_team, invited_user.email)

    request = RequestFactory().get("/")
    request.user = invited_user
    request.session = SessionStore()

    notifications = get_notifications(request)

    assert [n.type for n in notifications] == ["pending_invitation"]
    assert inviting_team.display_name in notifications[0].message


@pytest.mark.django_db
def test_the_notification_links_to_where_invitations_are_accepted(invited_user: User, inviting_team: Team) -> None:
    """Not the active workspace's member list, which holds no invitation of theirs."""
    other_team = Team.objects.create(name="Somewhere Else")
    Member.objects.create(team=other_team, user=invited_user, role="owner")
    _invite(inviting_team, invited_user.email)

    request = RequestFactory().get("/")
    request.user = invited_user
    request.session = SessionStore()
    request.session["current_team"] = {"key": other_team.key, "role": "owner"}

    notifications = get_notifications(request)

    assert notifications[0].action_url == reverse("core:settings")


@pytest.mark.django_db
def test_an_auto_accepted_invitation_tells_the_user(invited_user: User, inviting_team: Team) -> None:
    """A new user is put in the workspace and the invitation is deleted, so
    nothing downstream can announce it. The acceptance has to say so itself."""
    _invite(inviting_team, invited_user.email, role="admin")

    request = RequestFactory().get("/")
    request.user = invited_user
    request.session = SessionStore()
    request._messages = FallbackStorageStub()

    accepted = _accept_pending_invitations(invited_user, request)

    assert len(accepted) == 1
    assert Member.objects.filter(user=invited_user, team=inviting_team).exists()
    assert not Invitation.objects.filter(email=invited_user.email).exists()
    assert accepted[0]["announced"] is True
    assert [str(m) for m in request._messages.stored] == ["You have joined Lithium Labs as admin"]


class FallbackStorageStub:
    """Collects messages without needing MessageMiddleware on a bare request."""

    def __init__(self) -> None:
        self.stored: list[object] = []

    def add(self, level: int, message: str, extra_tags: str = "") -> None:
        self.stored.append(message)


@pytest.mark.django_db
def test_an_existing_member_is_not_auto_accepted(invited_user: User, inviting_team: Team) -> None:
    """The auto-accept is a first-login convenience; anyone else chooses."""
    other_team = Team.objects.create(name="Already In One")
    Member.objects.create(team=other_team, user=invited_user, role="owner")
    _invite(inviting_team, invited_user.email)

    request = RequestFactory().get("/")
    request.user = invited_user
    request.session = SessionStore()

    assert _accept_pending_invitations(invited_user, request) == []
    assert Invitation.objects.filter(email=invited_user.email).exists()


@pytest.mark.django_db
def test_a_login_without_message_storage_still_completes(
    invited_user: User, inviting_team: Team, client: Client
) -> None:
    """force_login builds a request with no message store, and announcing the
    acceptance must never be the thing that stops someone signing in."""
    _invite(inviting_team, invited_user.email)

    client.force_login(invited_user)
    response = client.get(reverse("core:settings"), follow=True)

    assert response.status_code == 200
    assert Member.objects.filter(user=invited_user, team=inviting_team).exists()


@pytest.mark.django_db
def test_a_login_with_no_message_storage_records_that_it_said_nothing(invited_user: User, inviting_team: Team) -> None:
    """The accept-invite view reads this flag to decide whether it still has to
    announce the join, so a silent acceptance must not claim otherwise."""
    _invite(inviting_team, invited_user.email)

    request = RequestFactory().get("/")
    request.user = invited_user
    request.session = SessionStore()

    accepted = _accept_pending_invitations(invited_user, request)

    assert accepted[0]["announced"] is False
