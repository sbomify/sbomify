"""Being privileged in one workspace must not carry into another.

TeamRoleRequiredMixin authorizes against the workspace in the *session*, while
the handlers act on the workspace named in the *URL*. Those are not the same
thing, and `member` is the first non-guest role below ADMINISTER — get_team()
turns guests away, so before it existed this gap had no one to fall through it.
"""

import pytest
from django.urls import reverse

from sbomify.apps.teams.models import Member, Team


@pytest.fixture
def home(db):
    return Team.objects.create(name="Home Workspace")


@pytest.fixture
def other(db):
    return Team.objects.create(name="Other Workspace")


@pytest.fixture
def two_hatted_user(db, django_user_model, home, other):
    """Owner of one workspace, ordinary member of another."""
    user = django_user_model.objects.create_user(
        username="twohats", email="twohats@test.com", password="password"
    )
    Member.objects.create(user=user, team=home, role="owner", is_default_team=True)
    Member.objects.create(user=user, team=other, role="member", is_default_team=False)
    return user


def _session_for(client, team, role):
    session = client.session
    session["current_team"] = {"key": team.key, "name": team.name, "role": role, "id": team.id}
    session["user_teams"] = {team.key: {"role": role, "name": team.name}}
    session.save()


@pytest.mark.django_db
def test_owner_elsewhere_cannot_rename_a_workspace_they_are_only_a_member_of(client, two_hatted_user, home, other):
    client.force_login(two_hatted_user)
    _session_for(client, home, "owner")

    response = client.post(
        reverse("teams:team_general", kwargs={"team_key": other.key}),
        {"action": "update_name", "name": "Renamed By An Outsider"},
    )

    other.refresh_from_db()
    assert other.name == "Other Workspace", "a member renamed a workspace using their role in a different one"
    assert response.status_code in (403, 302)


@pytest.mark.django_db
def test_owner_elsewhere_cannot_change_another_workspaces_freshness_policy(client, two_hatted_user, home, other):
    client.force_login(two_hatted_user)
    _session_for(client, home, "owner")

    client.post(
        reverse("teams:team_general", kwargs={"team_key": other.key}),
        {"action": "update_name", "name": other.name, "sbom_freshness_days": 1},
    )

    other.refresh_from_db()
    assert other.sbom_freshness_days is None


@pytest.mark.django_db
def test_capability_flags_describe_the_workspace_the_page_is_about(client, two_hatted_user, home, other):
    """The template flags must match the page, not the session.

    Otherwise the settings page for a workspace you are merely a member of
    renders the admin controls of the workspace you happen to have selected,
    and every one of them 403s when used — the UI/enforcement split this whole
    change set exists to close.
    """
    from sbomify.apps.core.context_processors import team_context

    client.force_login(two_hatted_user)
    _session_for(client, home, "owner")

    response = client.get(reverse("teams:team_settings", kwargs={"team_key": other.key}))
    request = response.wsgi_request

    context = team_context(request)

    assert context["team"].key == other.key
    assert context["workspace_role"] == "member"
    assert context["can_administer"] is False
    assert context["can_delete"] is False
    assert context["is_owner"] is False
    assert context["can_manage"] is True


@pytest.mark.django_db
def test_flags_still_come_from_the_session_when_the_url_names_no_workspace(client, two_hatted_user, home):
    """Pages that aren't workspace-scoped keep working off the session."""
    from sbomify.apps.core.context_processors import team_context

    client.force_login(two_hatted_user)
    _session_for(client, home, "owner")

    response = client.get(reverse("core:dashboard"))
    context = team_context(response.wsgi_request)

    assert context["team"].key == home.key
    assert context["is_owner"] is True


@pytest.mark.django_db
def test_a_member_cannot_delete_a_workspace_invitation(client, django_user_model, home):
    """Managing invitations is ADMINISTER, and the settings view is only MANAGE.

    TeamSettingsView was widened to MANAGE so members could reach their own
    tabs, on the stated basis that every POST sub-action re-checks ADMINISTER
    for itself. _delete_invitation did not, so a member could cancel any
    invitation in the workspace — including an owner-level one — with a crafted
    _method=DELETE post.
    """
    from datetime import timedelta

    from django.utils import timezone

    from sbomify.apps.teams.models import Invitation

    member_user = django_user_model.objects.create_user(
        username="plainmember", email="plainmember@test.com", password="password"
    )
    Member.objects.create(user=member_user, team=home, role="member", is_default_team=True)

    invitation = Invitation.objects.create(
        team=home, email="incoming-owner@example.com", role="owner",
        expires_at=timezone.now() + timedelta(days=7),
    )

    client.force_login(member_user)
    _session_for(client, home, "member")

    client.post(
        reverse("teams:team_settings", kwargs={"team_key": home.key}),
        {"_method": "DELETE", "invitation_id": invitation.id},
    )

    assert Invitation.objects.filter(pk=invitation.pk).exists(), (
        "a member deleted a workspace invitation; managing invitations is ADMINISTER"
    )
