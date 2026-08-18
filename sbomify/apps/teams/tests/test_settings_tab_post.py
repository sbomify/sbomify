"""Every form on a settings section posts back to that section's own URL.

Settings moved from one page of hidden panes to one page per section, and the
per-section route carries a ``tab``. ``TeamSettingsView.get`` was given the
parameter; ``post`` was not, so Django handed it a keyword argument it did not
declare and the request died in ``View.dispatch`` with a ``TypeError`` before
reaching any of this view's code. Removing a member and cancelling an invitation
are the two forms that post to ``request.path``, and both 500ed.

The tests go through the URL rather than calling the handler, because calling
``view.post(request, team_key)`` directly is exactly the call that worked while
production was broken.
"""

from __future__ import annotations

import pytest
from django.test import Client

from sbomify.apps.core.tests.shared_fixtures import (  # noqa: F401
    setup_authenticated_client_session,
)
from sbomify.apps.teams.models import Invitation, Member
from sbomify.apps.teams.settings_tabs import SETTINGS_TABS


@pytest.fixture
def owner_client(sample_team_with_owner_member: Member) -> tuple[Client, Member]:  # noqa: F811
    client = Client()
    client.force_login(sample_team_with_owner_member.user)
    setup_authenticated_client_session(
        client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
    )
    return client, sample_team_with_owner_member


@pytest.mark.django_db
def test_cancelling_an_invitation_from_the_members_tab(owner_client: tuple[Client, Member]) -> None:
    """The reported failure, end to end."""
    client, owner = owner_client
    invitation = Invitation.objects.create(team=owner.team, email="luc@example.test", role="admin")

    response = client.post(
        f"/workspaces/{owner.team.key}/settings/members",
        {"_method": "DELETE", "invitation_id": invitation.id, "active_tab": "members"},
    )

    assert response.status_code == 302
    assert not Invitation.objects.filter(pk=invitation.pk).exists()


@pytest.mark.django_db
def test_removing_a_member_from_the_members_tab(owner_client: tuple[Client, Member]) -> None:
    """The other form on the same page, which posts to the same URL."""
    from django.contrib.auth import get_user_model

    client, owner = owner_client
    victim = get_user_model().objects.create_user(username="removable", email="removable@example.test")
    membership = Member.objects.create(user=victim, team=owner.team, role="admin")

    response = client.post(
        f"/workspaces/{owner.team.key}/settings/members",
        {"_method": "DELETE", "member_id": membership.id, "active_tab": "members"},
    )

    assert response.status_code == 302
    assert not Member.objects.filter(pk=membership.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("tab", [tab.key for tab in SETTINGS_TABS])
def test_no_section_url_rejects_a_post(owner_client: tuple[Client, Member], tab: str) -> None:
    """Posting to any section is handled, not refused by the dispatcher.

    Only the members tab posts to ``request.path`` today, so pinning that one
    alone would let the next section that does so reintroduce the same 500. An
    unrecognised body is answered with "Invalid request method" and a redirect,
    which is this view's own reply — a 500 here means the request never arrived.
    """
    client, owner = owner_client

    response = client.post(f"/workspaces/{owner.team.key}/settings/{tab}", {})

    assert response.status_code == 302


@pytest.mark.django_db
def test_a_form_without_active_tab_returns_to_its_own_section(owner_client: tuple[Client, Member]) -> None:
    """The URL knows the section even when the form forgets to say so.

    ``active_tab`` is a hidden field every settings form is supposed to carry.
    Falling back to the tab in the URL means one that forgets it returns to the
    page it was submitted from instead of the first section in the list.
    """
    client, owner = owner_client
    invitation = Invitation.objects.create(team=owner.team, email="luc@example.test", role="guest")

    response = client.post(
        f"/workspaces/{owner.team.key}/settings/members",
        {"_method": "DELETE", "invitation_id": invitation.id},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/settings/members")
