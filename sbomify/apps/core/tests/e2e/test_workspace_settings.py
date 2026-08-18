"""Snapshots for the workspace pages: settings sections, the workspace list,
suppliers and the invite form.

The settings sections are each their own URL, so one case per section rather
than one case that clicks through them. General, tokens and branding load their
body over HTMX, which is why every case waits for the network to go quiet before
the shot is taken.
"""

import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.teams.models import Invitation, Supplier


@pytest.fixture
def workspace_with_invitations(team_with_business_plan):  # noqa: F811
    """Two pending invitations, so the members section shows the pending list
    and the tab badge that counts it rather than the empty state."""
    Invitation.objects.create(team=team_with_business_plan, email="ada@example.com", role="admin")
    Invitation.objects.create(team=team_with_business_plan, email="grace@example.com", role="guest")
    return team_with_business_plan


@pytest.fixture
def workspace_with_suppliers(team_with_business_plan):  # noqa: F811
    """Three suppliers covering the row's states: a full record, one with no
    contact and one with no website."""
    Supplier.objects.create(
        team=team_with_business_plan,
        name="Acme Components",
        contact_name="Ada Lovelace",
        contact_email="ada@acme.example",
        website="https://acme.example",
        notes="Ships a CycloneDX SBOM with every release.",
    )
    Supplier.objects.create(
        team=team_with_business_plan,
        name="Bolt Industrial",
        website="https://bolt.example",
    )
    Supplier.objects.create(
        team=team_with_business_plan,
        name="Cinder Systems",
        contact_name="Grace Hopper",
        contact_email="grace@cinder.example",
    )
    return team_with_business_plan


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestWorkspaceSettingsSnapshot:
    """One case per settings section."""

    def _shoot(self, page: Page, snapshot, width: int, url: str) -> None:
        page.goto(url)
        page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(page, width=width)
        current = snapshot.take_screenshot(page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_workspace_settings_general_snapshot(
        self,
        authenticated_page: Page,
        team_with_business_plan,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        self._shoot(authenticated_page, snapshot, width, f"/workspaces/{team_with_business_plan.key}/settings/general")

    def test_workspace_settings_members_snapshot(
        self,
        authenticated_page: Page,
        workspace_with_invitations,
        snapshot,
        width: int,
    ) -> None:
        self._shoot(
            authenticated_page, snapshot, width, f"/workspaces/{workspace_with_invitations.key}/settings/members"
        )

    def test_workspace_settings_tokens_snapshot(
        self,
        authenticated_page: Page,
        team_with_business_plan,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        self._shoot(authenticated_page, snapshot, width, f"/workspaces/{team_with_business_plan.key}/settings/tokens")

    def test_workspace_settings_branding_snapshot(
        self,
        authenticated_page: Page,
        team_with_business_plan,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        self._shoot(authenticated_page, snapshot, width, f"/workspaces/{team_with_business_plan.key}/settings/branding")

    def test_workspace_settings_billing_snapshot(
        self,
        authenticated_page: Page,
        team_with_business_plan,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        self._shoot(authenticated_page, snapshot, width, f"/workspaces/{team_with_business_plan.key}/settings/billing")

    def test_workspace_settings_account_snapshot(
        self,
        authenticated_page: Page,
        team_with_business_plan,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        self._shoot(authenticated_page, snapshot, width, f"/workspaces/{team_with_business_plan.key}/settings/account")


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestWorkspaceListSnapshot:
    def test_workspaces_dashboard_snapshot(
        self,
        authenticated_page: Page,
        team_with_business_plan,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/workspaces/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestSuppliersListSnapshot:
    def test_suppliers_list_snapshot(
        self,
        authenticated_page: Page,
        workspace_with_suppliers,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/workspaces/{workspace_with_suppliers.key}/suppliers")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestWorkspaceInviteSnapshot:
    def test_workspace_invite_snapshot(
        self,
        authenticated_page: Page,
        team_with_business_plan,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/workspaces/invite/{team_with_business_plan.key}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
