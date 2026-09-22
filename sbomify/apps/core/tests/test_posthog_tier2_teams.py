"""Tier 2 PostHog tests for ``team:*`` and ``api_token:*`` events."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.tests.posthog_helpers import (
    assert_workspace_attribution,
    called_events,
    find_call,
    patch_capture,
)
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Invitation, Member, Team


@pytest.mark.django_db(transaction=True)
def test_invite_member_captures_team_member_invited(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    mock_capture = patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    assert team_with_business_plan.key is not None
    response = client.post(
        reverse("teams:invite_user", kwargs={"team_key": team_with_business_plan.key}),
        data={"email": "new-colleague@example.com", "role": "admin"},
    )

    assert response.status_code in (200, 302)
    assert "team:member_invited" in called_events(mock_capture)
    invite_call = find_call(mock_capture, "team:member_invited")
    assert invite_call.args[2]["invited_email_domain"] == "example.com"
    assert invite_call.args[2]["role"] == "admin"
    assert_workspace_attribution(mock_capture, "team:member_invited", team_with_business_plan.key)


@pytest.mark.django_db(transaction=True)
def test_accept_invite_captures_team_member_invitation_accepted(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """The explicit accept_invite view fires the event for existing users.

    Invitee has a pre-existing workspace so the user_logged_in auto-accept
    signal short-circuits; the capture under test is the view-level one.
    """
    from django.contrib.auth import get_user_model

    UserModel = get_user_model()
    invitee = UserModel.objects.create_user(username="invitee", email="invitee@example.com", password="pw")

    # Pre-existing membership skips the auto-accept signal path.
    other_team = Team.objects.create(name="Other Workspace", billing_plan="business")
    Member.objects.create(team=other_team, user=invitee, role="owner", is_default_team=True)

    invitation = Invitation.objects.create(
        team=team_with_business_plan,
        email=invitee.email,
        role="admin",
    )

    mock_capture = patch_capture(mocker)
    client = Client()
    client.force_login(invitee)

    response = client.get(reverse("teams:accept_invite", kwargs={"invite_token": str(invitation.token)}))

    assert response.status_code == 302, f"Unexpected status {response.status_code}: {response.content!r}"
    assert Member.objects.filter(team=team_with_business_plan, user=invitee).exists()
    assert "team:member_invitation_accepted" in called_events(mock_capture)


@pytest.mark.django_db(transaction=True)
def test_auto_accept_invitation_captures_team_member_invitation_accepted(
    mocker: MockerFixture,
    team_with_business_plan: Team,
) -> None:
    """The user_logged_in auto-accept path fires the event for new-user invitations.

    Invite-only signups land via this path: a fresh user (no memberships)
    logs in and the signal handler auto-accepts every pending invitation.
    Without a capture here the most common invitation-acceptance flow would
    never be measured.
    """
    from django.contrib.auth import get_user_model

    UserModel = get_user_model()
    invitee = UserModel.objects.create_user(username="newcomer", email="newcomer@example.com", password="pw")
    assert not Member.objects.filter(user=invitee).exists()

    Invitation.objects.create(
        team=team_with_business_plan,
        email=invitee.email,
        role="guest",
    )

    mock_capture = patch_capture(mocker)
    client = Client()
    client.force_login(invitee)

    assert Member.objects.filter(team=team_with_business_plan, user=invitee).exists()
    assert "team:member_invitation_accepted" in called_events(mock_capture)
    call = find_call(mock_capture, "team:member_invitation_accepted")
    assert call.args[2]["role"] == "guest"


@pytest.mark.django_db(transaction=True)
def test_remove_member_captures_team_member_removed(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    from django.contrib.auth import get_user_model

    UserModel = get_user_model()
    other_user = UserModel.objects.create_user(username="other", email="other@example.com", password="pw")
    membership = Member.objects.create(team=team_with_business_plan, user=other_user, role="admin")

    mock_capture = patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    response = client.post(reverse("teams:team_membership_delete", kwargs={"membership_id": membership.id}))

    assert response.status_code in (200, 302)
    assert "team:member_removed" in called_events(mock_capture)
    call = find_call(mock_capture, "team:member_removed")
    assert call.args[2]["role"] == "admin"
    assert call.args[2]["self_removal"] is False


@pytest.mark.django_db(transaction=True)
def test_settings_view_member_remove_also_fires_event(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """remove_member_safely is reused by TeamSettingsView; verify that path also captures."""
    from django.contrib.auth import get_user_model

    UserModel = get_user_model()
    other_user = UserModel.objects.create_user(username="other2", email="other2@example.com", password="pw")
    membership = Member.objects.create(team=team_with_business_plan, user=other_user, role="admin")

    mock_capture = patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    assert team_with_business_plan.key is not None
    response = client.post(
        reverse("teams:team_settings", kwargs={"team_key": team_with_business_plan.key}),
        data={"_method": "DELETE", "member_id": membership.id, "active_tab": "members"},
    )

    assert response.status_code in (200, 302)
    assert "team:member_removed" in called_events(mock_capture)


@pytest.mark.django_db(transaction=True)
def test_role_change_captures_team_role_changed(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """Saving an existing Member with a new role fires ``team:role_changed``."""
    from django.contrib.auth import get_user_model

    UserModel = get_user_model()
    other_user = UserModel.objects.create_user(username="role_target", email="role@example.com", password="pw")
    membership = Member.objects.create(team=team_with_business_plan, user=other_user, role="guest")

    mock_capture = patch_capture(mocker)

    membership.role = "admin"
    membership.save()

    role_calls = [c for c in mock_capture.call_args_list if c.args[1] == "team:role_changed"]
    assert len(role_calls) == 1, f"Expected exactly one team:role_changed event, got {len(role_calls)}"
    props = role_calls[0].args[2]
    assert props["from_role"] == "guest"
    assert props["to_role"] == "admin"
    assert team_with_business_plan.key is not None
    assert_workspace_attribution(mock_capture, "team:role_changed", team_with_business_plan.key)


@pytest.mark.django_db(transaction=True)
def test_role_change_no_op_save_does_not_capture(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """Re-saving a Member without changing role must not fire ``team:role_changed``."""
    from django.contrib.auth import get_user_model

    UserModel = get_user_model()
    other_user = UserModel.objects.create_user(username="noop_role", email="noop@example.com", password="pw")
    membership = Member.objects.create(team=team_with_business_plan, user=other_user, role="admin")

    mock_capture = patch_capture(mocker)

    membership.save()

    assert "team:role_changed" not in called_events(mock_capture)


@pytest.mark.django_db(transaction=True)
def test_role_change_followed_by_other_field_save_does_not_refire(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """A second save touching a non-role field must NOT re-fire team:role_changed.

    Regression: ``_sbomify_old_role`` used to survive on the instance
    after a successful role-change fire, so a later
    ``save(update_fields=["is_default_team"])`` would see the stale
    snapshot and re-emit the event even though role didn't change.
    """
    from django.contrib.auth import get_user_model

    UserModel = get_user_model()
    other_user = UserModel.objects.create_user(username="leak_test", email="leak@example.com", password="pw")
    membership = Member.objects.create(team=team_with_business_plan, user=other_user, role="guest")

    mock_capture = patch_capture(mocker)

    # First save: actual role change → event fires once
    membership.role = "admin"
    membership.save()
    role_calls_after_first = [c for c in mock_capture.call_args_list if c.args[1] == "team:role_changed"]
    assert len(role_calls_after_first) == 1

    # Second save: unrelated field change → must NOT re-fire
    membership.is_default_team = True
    membership.save(update_fields=["is_default_team"])

    role_calls_after_second = [c for c in mock_capture.call_args_list if c.args[1] == "team:role_changed"]
    assert len(role_calls_after_second) == 1, (
        f"Expected only the first save to fire team:role_changed, got {len(role_calls_after_second)} total"
    )
    # Snapshot attr must be cleared after the first fire
    assert not hasattr(membership, "_sbomify_old_role")


@pytest.mark.django_db(transaction=True)
def test_role_change_update_fields_without_role_skips_snapshot(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """``save(update_fields=[other])`` must not even snapshot the role.

    Pre_save would otherwise do an extra DB query on every Member.save()
    that touched a different field (last_login_team, is_default_team).
    """
    from django.contrib.auth import get_user_model

    UserModel = get_user_model()
    other_user = UserModel.objects.create_user(username="other_field", email="other@example.com", password="pw")
    membership = Member.objects.create(team=team_with_business_plan, user=other_user, role="admin", is_default_team=False)

    mock_capture = patch_capture(mocker)

    # Save with update_fields excluding 'role' — snapshot must be skipped
    membership.is_default_team = True
    membership.save(update_fields=["is_default_team"])

    assert "team:role_changed" not in called_events(mock_capture)
    # Confirm the snapshot attr was NOT set
    assert not hasattr(membership, "_sbomify_old_role")


@pytest.mark.django_db(transaction=True)
def test_create_access_token_captures_api_token_created(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    mock_capture = patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    assert team_with_business_plan.key is not None
    response = client.post(
        reverse("teams:team_tokens", kwargs={"team_key": team_with_business_plan.key}),
        data={"description": "test-token"},
    )

    assert response.status_code == 200
    assert "api_token:created" in called_events(mock_capture)
    call = find_call(mock_capture, "api_token:created")
    # Token description is treated as PII and never forwarded to PostHog.
    assert "token_name" not in (call.args[2] or {})


@pytest.mark.django_db(transaction=True)
def test_delete_access_token_captures_api_token_deleted(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    token = AccessToken.objects.create(
        encoded_token="dummy",
        user=sample_user,
        description="d",
        team=team_with_business_plan,
    )

    mock_capture = patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    response = client.delete(reverse("core:delete_access_token", kwargs={"token_id": token.id}))

    assert response.status_code == 200
    assert "api_token:deleted" in called_events(mock_capture)


@pytest.mark.django_db(transaction=True)
def test_custom_domain_first_time_set_captures_event(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """team:custom_domain_added fires when a workspace gets its first custom domain."""
    assert team_with_business_plan.custom_domain in (None, "")

    mock_capture = patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    assert team_with_business_plan.key is not None
    response = client.put(
        f"/api/v1/workspaces/{team_with_business_plan.key}/domain",
        data='{"domain": "app.example.com"}',
        content_type="application/json",
    )

    assert response.status_code == 200, response.content
    assert "team:custom_domain_added" in called_events(mock_capture)
    assert_workspace_attribution(mock_capture, "team:custom_domain_added", team_with_business_plan.key)


@pytest.mark.django_db
def test_custom_domain_resave_same_value_does_not_capture(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """Re-saving an existing domain (no change) must not fire team:custom_domain_added."""
    team_with_business_plan.custom_domain = "existing.example.com"
    team_with_business_plan.save(update_fields=["custom_domain"])

    mock_capture = patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    assert team_with_business_plan.key is not None
    response = client.put(
        f"/api/v1/workspaces/{team_with_business_plan.key}/domain",
        data='{"domain": "existing.example.com"}',
        content_type="application/json",
    )

    assert response.status_code == 200, response.content
    assert "team:custom_domain_added" not in called_events(mock_capture)


@pytest.mark.django_db
def test_custom_domain_change_to_different_value_does_not_capture(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """Switching from one custom domain to another is not a first-time set; event must not fire."""
    team_with_business_plan.custom_domain = "old.example.com"
    team_with_business_plan.save(update_fields=["custom_domain"])

    mock_capture = patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    assert team_with_business_plan.key is not None
    response = client.put(
        f"/api/v1/workspaces/{team_with_business_plan.key}/domain",
        data='{"domain": "new.example.com"}',
        content_type="application/json",
    )

    assert response.status_code == 200, response.content
    assert "team:custom_domain_added" not in called_events(mock_capture)
