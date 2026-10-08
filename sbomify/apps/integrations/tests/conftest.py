from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.integrations.models import Integration


@pytest.fixture
def vanta_credentials(settings):
    """A deployment that holds Vanta OAuth credentials.

    Without these the provider is "not available here" and every connect path
    short-circuits, so almost every test in this app needs them.
    """
    settings.VANTA_CLIENT_ID = "vci_test"
    settings.VANTA_CLIENT_SECRET = "vcs_test"
    settings.VANTA_OAUTH_AUTHORIZE_URL = "https://app.vanta.example/oauth/authorize"
    settings.VANTA_OAUTH_TOKEN_URL = "https://api.vanta.example/oauth/token"
    settings.VANTA_API_BASE_URL = "https://api.vanta.example"
    return settings


@pytest.fixture
def connected_vanta(sample_team_with_owner_member) -> Integration:
    return Integration.objects.create(
        team=sample_team_with_owner_member.team,
        provider=Integration.Provider.VANTA,
        access_token="vat_live",
        refresh_token="vrt_live",
        token_expires_at=timezone.now() + timedelta(hours=1),
        connected_by=sample_team_with_owner_member.user,
    )


@pytest.fixture
def admin_client_for_team(sample_team_with_owner_member) -> Client:
    client = Client()
    setup_authenticated_client_session(
        client, sample_team_with_owner_member.team, sample_team_with_owner_member.user
    )
    return client
