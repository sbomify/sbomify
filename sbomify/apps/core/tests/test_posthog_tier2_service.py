"""Tier 2 PostHog tests for the ``capture_for_request`` service helper.

These exercise the helper's guards (anonymous distinct_id, disabled
PostHog) and the ``search:performed`` view — the only Tier 2 site that
doesn't sit cleanly under a single domain.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.tests.posthog_helpers import called_events, find_call, patch_capture
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Team


@pytest.mark.django_db
def test_search_captures_search_performed(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    mock_capture = patch_capture(mocker)
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    response = client.get(reverse("core:search") + "?q=acme")

    assert response.status_code == 200
    assert "search:performed" in called_events(mock_capture)
    call = find_call(mock_capture, "search:performed")
    assert call.args[2]["query_length"] == 4


@pytest.mark.django_db
def test_capture_for_request_skips_anonymous_distinct_id(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """Capture is skipped when distinct_id resolves to ``anonymous`` AND no team_key is supplied.

    ``capture_for_request`` prefers ``team_key`` as the distinct_id when
    provided (workspace-level attribution per PR #822). The anonymous guard
    only kicks in for events without a team_key — e.g. user-scoped events
    like ``user:account_deleted``. ``search:performed`` does pass team_key,
    so to exercise the guard we patch the helper signature directly.
    """
    from sbomify.apps.core.posthog_service import capture_for_request

    mocker.patch("sbomify.apps.core.posthog_service.is_enabled", return_value=True)
    mocker.patch("sbomify.apps.core.posthog_service.get_distinct_id", return_value="anonymous")
    mock_capture = mocker.patch("sbomify.apps.core.posthog_service.capture")

    # Simulate a user-scoped event (no team_key) with an anonymous request.
    fake_request = mocker.MagicMock()
    capture_for_request(fake_request, "user:account_deleted")

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
