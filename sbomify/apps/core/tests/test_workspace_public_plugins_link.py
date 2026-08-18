"""The Trust Center's scanning prompt must land on *this* workspace's plugins.

``is_workspace_admin`` is computed against the workspace whose page is being
viewed, not the one selected in the session, so an owner of two workspaces
browsing A's public page while B is current sees the prompt. The Plugins page is
scoped to the session's current workspace, so a bare link to it would have
offered to enable scanning on B.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import (  # noqa: F401
    setup_authenticated_client_session,
)
from sbomify.apps.teams.models import Member, Team


@pytest.fixture
def two_workspaces(sample_team_with_owner_member: Member) -> tuple[Team, Team, Client]:  # noqa: F811
    """A user owning two public workspaces, with the *other* one selected."""
    user = sample_team_with_owner_member.user
    viewed = sample_team_with_owner_member.team
    viewed.is_public = True
    # Otherwise the onboarding middleware intercepts the redirect and the test
    # measures plan selection rather than which workspace was switched to.
    viewed.has_selected_billing_plan = True
    viewed.has_completed_wizard = True
    viewed.save(update_fields=["is_public", "has_selected_billing_plan", "has_completed_wizard"])

    selected = Team.objects.create(name="The Other Workspace")
    Member.objects.create(user=user, team=selected, role="owner")

    client = Client()
    client.force_login(user)
    setup_authenticated_client_session(client, selected, user)
    return viewed, selected, client


@pytest.mark.django_db
def test_the_prompt_switches_workspace_before_landing_on_plugins(
    two_workspaces: tuple[Team, Team, Client],
) -> None:
    viewed, selected, client = two_workspaces

    response = client.get(reverse("core:workspace_public", kwargs={"workspace_key": viewed.key}))
    html = response.content.decode()

    assert response.status_code == 200
    # The prompt only renders for an admin of the viewed workspace with no
    # scanner enabled, which is this fixture.
    assert "Enable vulnerability scanning" in html

    switch = reverse("teams:switch_team", kwargs={"team_key": viewed.key})
    plugins = reverse("plugins:plugins_page")
    assert f'href="{switch}?next={plugins}"' in html

    # The bare link is what would have taken them to the selected workspace's
    # plugins instead of the viewed one's.
    assert f'href="{plugins}"' not in html


@pytest.mark.django_db
def test_following_it_selects_the_viewed_workspace(
    two_workspaces: tuple[Team, Team, Client],
) -> None:
    """Switching is what makes the destination correct, so exercise the hop.

    Only the one redirect is asserted. Where the Plugins page sends an
    unonboarded workspace next is a separate gate that the previous
    ``Settings -> Plugins`` link met in the same way.
    """
    viewed, selected, client = two_workspaces
    assert client.session["current_team"]["key"] == selected.key

    plugins = reverse("plugins:plugins_page")
    response = client.get(f"{reverse('teams:switch_team', kwargs={'team_key': viewed.key})}?next={plugins}")

    assert response.status_code == 302
    assert response.headers["Location"] == plugins
    assert client.session["current_team"]["key"] == viewed.key


@pytest.mark.django_db
def test_switching_to_a_workspace_missing_from_a_stale_session(
    two_workspaces: tuple[Team, Team, Client],
) -> None:
    """The prompt is rendered from a live membership check, the switch read a
    session map written at login, and the two can disagree.

    A membership granted since login is absent from ``user_teams``, and the
    lookup was unguarded — so the link this PR adds could hand ``switch_team`` a
    key it would ``KeyError`` on. Every previous caller built its link from that
    same map and could not.
    """
    viewed, _selected, client = two_workspaces
    session = client.session
    session["user_teams"] = {k: v for k, v in session["user_teams"].items() if k != viewed.key}
    session.save()
    assert viewed.key not in client.session["user_teams"]

    response = client.get(reverse("teams:switch_team", kwargs={"team_key": viewed.key}))

    assert response.status_code == 302
    assert client.session["current_team"]["key"] == viewed.key


@pytest.mark.django_db
def test_switching_to_a_workspace_the_user_does_not_belong_to(
    two_workspaces: tuple[Team, Team, Client],
) -> None:
    """Refreshing from the database must not become a way in.

    A key absent after the refresh means the membership is not there to find,
    which is a redirect rather than a switch.
    """
    _viewed, _selected, client = two_workspaces
    stranger = Team.objects.create(name="Someone Else's Workspace")

    response = client.get(reverse("teams:switch_team", kwargs={"team_key": stranger.key}))

    assert response.status_code == 302
    assert client.session["current_team"]["key"] != stranger.key
