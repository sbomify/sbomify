"""Tests for renaming the Trust Center subdomain slug."""

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import Member, Team


def _post_slug(client: Client, team: Team, new_slug: str):
    return client.post(
        reverse("teams:team_settings", kwargs={"team_key": team.key}),
        {"slug_action": "update", "slug": new_slug, "active_tab": "trust-center"},
    )


def _messages(response) -> list[str]:
    return [str(m) for m in get_messages(response.wsgi_request)]


@pytest.mark.django_db
def test_owner_can_rename_slug_on_community_plan(sample_team_with_owner_member: Member):  # noqa: F811
    """Community workspaces have no billing_plan/billing_plan_limits and empty branding_info."""
    team = sample_team_with_owner_member.team
    team.slug = "old-slug"
    team.is_public = True
    team.save()

    client = Client()
    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

    response = _post_slug(client, team, "new-slug")

    assert response.status_code == 302
    team.refresh_from_db()
    assert team.slug == "new-slug", f"rename rejected: {_messages(response)}"


@pytest.mark.django_db
def test_owner_can_rename_slug_on_paid_plan(sample_team_with_owner_member: Member):  # noqa: F811
    """A live Trust Center on a paid plan, mirroring production."""
    team = sample_team_with_owner_member.team
    team.billing_plan = "business"
    team.billing_plan_limits = {
        "stripe_customer_id": "cus_test123",
        "stripe_subscription_id": "sub_test123",
        "subscription_status": "active",
    }
    team.slug = "acme"
    team.is_public = True
    team.save()

    client = Client()
    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

    response = _post_slug(client, team, "acme-corp")

    assert response.status_code == 302
    team.refresh_from_db()
    assert team.slug == "acme-corp", f"rename rejected: {_messages(response)}"


@pytest.mark.django_db
def test_rename_rejects_invalid_slug_format(sample_team_with_owner_member: Member):  # noqa: F811
    team = sample_team_with_owner_member.team
    team.slug = "acme"
    team.save()

    client = Client()
    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

    response = _post_slug(client, team, "-bad-slug-")

    team.refresh_from_db()
    assert team.slug == "acme"
    assert any("hyphen" in m for m in _messages(response))


@pytest.mark.django_db
def test_rename_rejects_reserved_slug(sample_team_with_owner_member: Member):  # noqa: F811
    from sbomify.apps.teams.models import RESERVED_SLUGS

    team = sample_team_with_owner_member.team
    team.slug = "acme"
    team.save()

    client = Client()
    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

    response = _post_slug(client, team, sorted(RESERVED_SLUGS)[0])

    team.refresh_from_db()
    assert team.slug == "acme"
    assert _messages(response), "expected an error message for a reserved slug"


@pytest.mark.django_db
def test_rename_rejects_slug_taken_by_another_workspace(sample_team_with_owner_member: Member):  # noqa: F811
    team = sample_team_with_owner_member.team
    team.slug = "acme"
    team.save()
    Team.objects.create(name="Other workspace", slug="taken")

    client = Client()
    setup_authenticated_client_session(client, team, sample_team_with_owner_member.user)

    response = _post_slug(client, team, "taken")

    team.refresh_from_db()
    assert team.slug == "acme"
    assert _messages(response), "expected an error message for a duplicate slug"


def _member_with_role(team: Team, role: str, username: str) -> Member:
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user(username=username, password="x")  # noqa: S106
    return Member.objects.create(user=user, team=team, role=role)


@pytest.mark.django_db
def test_admin_can_rename_slug(sample_team_with_owner_member: Member):  # noqa: F811
    """The slug is workspace configuration, so it is ADMINISTER, not owner-only."""
    team = sample_team_with_owner_member.team
    team.slug = "acme"
    team.save()

    admin = _member_with_role(team, "admin", "admin-user")

    client = Client()
    setup_authenticated_client_session(client, team, admin.user)

    response = _post_slug(client, team, "renamed-by-admin")

    assert response.status_code == 302
    team.refresh_from_db()
    assert team.slug == "renamed-by-admin"


@pytest.mark.django_db
def test_guest_cannot_rename_slug(sample_team_with_owner_member: Member):  # noqa: F811
    """Guests are rejected by TeamRoleRequiredMixin before the handler runs."""
    team = sample_team_with_owner_member.team
    team.slug = "acme"
    team.save()

    guest = _member_with_role(team, "guest", "guest-user")

    client = Client()
    setup_authenticated_client_session(client, team, guest.user)

    response = _post_slug(client, team, "hijacked")

    assert response.status_code == 403
    team.refresh_from_db()
    assert team.slug == "acme"
