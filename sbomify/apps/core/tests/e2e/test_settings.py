from typing import Any, Generator
from urllib.parse import urlparse

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client
from playwright.sync_api import BrowserContext, Page

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.models import Invitation, Team


@pytest.fixture
def invitation(sample_user) -> Generator[Invitation, None, None]:  # noqa: F811
    """An invitation waiting for the signed-in user, which is the only thing
    that keeps /settings on the settings page: with a workspace selected the
    view redirects into the workspace's own settings."""
    team = Team.objects.create(name="Contoso Industries")
    yield Invitation.objects.create(team=team, email=sample_user.email, role="admin")


@pytest.fixture
def access_tokens(sample_user) -> Generator[list[AccessToken], None, None]:  # noqa: F811
    """Two tokens, so the page shows its token table rather than its empty
    state."""
    yield [
        AccessToken.objects.create(
            user=sample_user,
            description=description,
            encoded_token=f"sbom_{description.lower().replace(' ', '_')}",
        )
        for description in ("CI/CD Pipeline Token", "Local scripts")
    ]


@pytest.fixture
def no_workspace_page(
    browser_context: BrowserContext,
    browser_base_url: str,
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan,  # noqa: F811
) -> Generator[Page, Any, None]:
    """A signed-in page with no workspace selected. The session is the one the
    shared fixture builds, minus current_team."""
    django_client = Client()
    setup_authenticated_client_session(django_client, team_with_business_plan, sample_user)

    session = django_client.session
    del session["current_team"]
    session.save()

    browser_context.add_cookies(
        [
            {
                "name": "sessionid",
                "value": session.session_key,
                "domain": urlparse(browser_base_url).hostname,
                "path": "/",
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            }
        ]
    )

    page_instance = browser_context.new_page()
    yield page_instance
    page_instance.close()


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestSettingsSnapshot:
    def test_settings_snapshot(
        self,
        no_workspace_page: Page,
        invitation,
        access_tokens,
        snapshot,
        width: int,
    ) -> None:
        no_workspace_page.goto("/settings")
        no_workspace_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(no_workspace_page, width=width)
        current = snapshot.take_screenshot(no_workspace_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
