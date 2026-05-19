"""Tier 2 PostHog tests for ``document:*`` events."""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture

from sbomify.apps.core.tests.posthog_helpers import called_events, patch_capture
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Team


@pytest.mark.django_db(transaction=True)
def test_reject_access_request_captures_document_access_denied(
    mocker: MockerFixture,
    team_with_business_plan: Team,
    sample_user: Any,
) -> None:
    """Rejecting a pending AccessRequest in the queue view fires ``document:access_denied``."""
    from django.contrib.auth import get_user_model

    from sbomify.apps.documents.access_models import AccessRequest

    UserModel = get_user_model()
    requester = UserModel.objects.create_user(username="rejected_user", email="rejected@example.com", password="pw")
    access_request = AccessRequest.objects.create(
        team=team_with_business_plan, user=requester, status=AccessRequest.Status.PENDING
    )

    mock_capture = patch_capture(mocker)
    # The reject path sends an email — patch the renderer so the test doesn't
    # depend on template files or SMTP fixtures.
    mocker.patch("sbomify.apps.documents.views.access_requests.render_to_string", return_value="<html />")
    mocker.patch("sbomify.apps.documents.views.access_requests.EmailMultiAlternatives")

    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    assert team_with_business_plan.key is not None
    response = client.post(
        reverse("documents:access_request_queue", kwargs={"team_key": team_with_business_plan.key}),
        data={"action": "reject", "request_id": str(access_request.id)},
    )

    assert response.status_code in (200, 302)
    assert "document:access_denied" in called_events(mock_capture)
