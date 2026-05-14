"""Smoke tests for PostHog Tier 2 event captures.

Each test verifies that the relevant view/flow invokes
``sbomify.apps.core.posthog_service.capture`` with the expected event name.

Patch target rationale: most capture sites use the ``capture_for_request``
helper, which in turn calls the module-level ``capture``. Patching
``capture`` therefore intercepts both helper-based and direct call sites
without needing per-site patching.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Invitation, Member, Team


def _patch_capture(mocker: MockerFixture) -> Any:
    mocker.patch("sbomify.apps.core.posthog_service.is_enabled", return_value=True)
    return mocker.patch("sbomify.apps.core.posthog_service.capture")


def _called_events(mock_capture: Any) -> list[str]:
    return [call.args[1] for call in mock_capture.call_args_list]


@pytest.mark.django_db
def test_invite_member_captures_team_member_invited(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    mock_capture = _patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    assert team_with_business_plan.key is not None
    response = client.post(
        reverse("teams:invite_user", kwargs={"team_key": team_with_business_plan.key}),
        data={"email": "new-colleague@example.com", "role": "admin"},
    )

    assert response.status_code in (200, 302)
    assert "team:member_invited" in _called_events(mock_capture)
    invite_call = next(c for c in mock_capture.call_args_list if c.args[1] == "team:member_invited")
    assert invite_call.args[2]["invited_email_domain"] == "example.com"
    assert invite_call.args[2]["role"] == "admin"


@pytest.mark.django_db
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

    mock_capture = _patch_capture(mocker)
    client = Client()
    client.force_login(invitee)

    response = client.get(reverse("teams:accept_invite", kwargs={"invite_token": str(invitation.token)}))

    assert response.status_code == 302, f"Unexpected status {response.status_code}: {response.content!r}"
    assert Member.objects.filter(team=team_with_business_plan, user=invitee).exists()
    assert "team:member_invitation_accepted" in _called_events(mock_capture)


@pytest.mark.django_db
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

    mock_capture = _patch_capture(mocker)
    client = Client()
    client.force_login(invitee)

    assert Member.objects.filter(team=team_with_business_plan, user=invitee).exists()
    assert "team:member_invitation_accepted" in _called_events(mock_capture)
    call = next(c for c in mock_capture.call_args_list if c.args[1] == "team:member_invitation_accepted")
    assert call.args[2]["role"] == "guest"


@pytest.mark.django_db
def test_remove_member_captures_team_member_removed(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    from django.contrib.auth import get_user_model

    UserModel = get_user_model()
    other_user = UserModel.objects.create_user(username="other", email="other@example.com", password="pw")
    membership = Member.objects.create(team=team_with_business_plan, user=other_user, role="admin")

    mock_capture = _patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    response = client.post(reverse("teams:team_membership_delete", kwargs={"membership_id": membership.id}))

    assert response.status_code in (200, 302)
    assert "team:member_removed" in _called_events(mock_capture)
    call = next(c for c in mock_capture.call_args_list if c.args[1] == "team:member_removed")
    assert call.args[2]["role"] == "admin"
    assert call.args[2]["self_removal"] is False


@pytest.mark.django_db
def test_create_access_token_captures_api_token_created(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    mock_capture = _patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    assert team_with_business_plan.key is not None
    response = client.post(
        reverse("teams:team_tokens", kwargs={"team_key": team_with_business_plan.key}),
        data={"description": "test-token"},
    )

    assert response.status_code == 200
    assert "api_token:created" in _called_events(mock_capture)
    call = next(c for c in mock_capture.call_args_list if c.args[1] == "api_token:created")
    # Token description is treated as PII and never forwarded to PostHog.
    assert "token_name" not in (call.args[2] or {})


@pytest.mark.django_db
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

    mock_capture = _patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    response = client.delete(reverse("core:delete_access_token", kwargs={"token_id": token.id}))

    assert response.status_code == 200
    assert "api_token:deleted" in _called_events(mock_capture)


@pytest.mark.django_db
def test_search_captures_search_performed(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    mock_capture = _patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    response = client.get(reverse("core:search") + "?q=acme")

    assert response.status_code == 200
    assert "search:performed" in _called_events(mock_capture)
    call = next(c for c in mock_capture.call_args_list if c.args[1] == "search:performed")
    assert call.args[2]["query_length"] == 4


@pytest.mark.django_db
def test_capture_for_request_skips_anonymous_distinct_id(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """Even on a view that fires events, capture is skipped when distinct_id is 'anonymous'.

    Targets the anonymous guard inside ``capture_for_request`` directly; just
    routing through a logged-out client would short-circuit the view via
    LoginRequiredMixin before the guard is exercised.
    """
    mocker.patch("sbomify.apps.core.posthog_service.is_enabled", return_value=True)
    mocker.patch("sbomify.apps.core.posthog_service.get_distinct_id", return_value="anonymous")
    mock_capture = mocker.patch("sbomify.apps.core.posthog_service.capture")

    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)
    response = client.get(reverse("core:search") + "?q=acme")

    assert response.status_code == 200
    assert mock_capture.call_count == 0


@pytest.mark.django_db
def test_capture_for_request_skips_when_disabled(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """When ``is_enabled()`` returns False, capture_for_request short-circuits early."""
    mocker.patch("sbomify.apps.core.posthog_service.is_enabled", return_value=False)
    mock_capture = mocker.patch("sbomify.apps.core.posthog_service.capture")

    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)
    response = client.get(reverse("core:search") + "?q=acme")

    assert response.status_code == 200
    assert mock_capture.call_count == 0


@pytest.mark.django_db
def test_handle_trial_period_emits_trial_expired_only_once(
    mocker: MockerFixture,
    team_with_business_plan: Team,
) -> None:
    """billing:trial_expired must fire exactly once per team, even on redelivered webhooks.

    Stripe can deliver multiple ``customer.subscription.updated`` events that
    still report ``status=trialing`` after we have already downgraded a team
    locally; we rely on a persistent marker in ``billing_plan_limits`` so the
    transition-only side effects do not run twice.
    """
    import datetime
    from unittest.mock import MagicMock

    from django.utils import timezone

    from sbomify.apps.billing.billing_processing import handle_trial_period

    mock_capture = _patch_capture(mocker)
    # The downgrade calls notify_team_owners → email_notifications.notify_trial_expired;
    # patch them out so the test does not depend on SMTP fixtures.
    mocker.patch("sbomify.apps.billing.billing_processing.email_notifications")
    mocker.patch("sbomify.apps.billing.billing_processing.handle_community_downgrade_visibility")

    subscription = MagicMock()
    subscription.status = "trialing"
    subscription.trial_end = int((timezone.now() - datetime.timedelta(days=1)).timestamp())

    assert handle_trial_period(subscription, team_with_business_plan) is True
    assert handle_trial_period(subscription, team_with_business_plan) is True

    trial_expired_calls = [c for c in mock_capture.call_args_list if c.args[1] == "billing:trial_expired"]
    assert len(trial_expired_calls) == 1, (
        f"Expected billing:trial_expired to fire exactly once, got {len(trial_expired_calls)} calls"
    )


@pytest.mark.django_db
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

    mock_capture = _patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    assert team_with_business_plan.key is not None
    response = client.post(
        reverse("teams:team_settings", kwargs={"team_key": team_with_business_plan.key}),
        data={"_method": "DELETE", "member_id": membership.id, "active_tab": "members"},
    )

    assert response.status_code in (200, 302)
    assert "team:member_removed" in _called_events(mock_capture)
