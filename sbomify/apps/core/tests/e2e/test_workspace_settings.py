"""Snapshots for the workspace pages: settings sections, the workspace list,
suppliers and the invite form.

Each settings section has its own URL. Snapshots cover the server-rendered
panels and wait for the remaining Trust Center modules before capture.
"""

from typing import Any

import pytest
from playwright.sync_api import Page

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.teams.models import ContactProfile, Invitation, Supplier


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

    @pytest.fixture(autouse=True)
    def enable_billing(self, settings: Any, mocker: Any) -> None:
        settings.BILLING = True
        settings.APP_BASE_URL = "https://app.example.com"
        mocker.patch("sbomify.apps.teams.views.team_settings.sync_subscription_from_stripe")
        mocker.patch(
            "sbomify.apps.billing.team_pricing_service.TeamPricingService.get_plan_pricing",
            return_value={"amount": "$15", "period": "/month", "billing_period": "monthly"},
        )
        mocker.patch(
            "sbomify.apps.billing.stripe_pricing_service.StripePricingService._refresh_pricing_from_stripe",
            return_value={},
        )

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
        AccessToken.objects.create(
            team=team_with_business_plan,
            user=team_with_business_plan.member_set.get(role="owner").user,
            description="CI publishing",
            encoded_token="snapshot-token",
        )
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

    def test_workspace_settings_parties_snapshot(
        self, authenticated_page: Page, team_with_business_plan: Any, snapshot: Any, width: int
    ) -> None:
        ContactProfile.objects.create(team=team_with_business_plan, name="Product contacts", is_default=True)
        ContactProfile.objects.create(team=team_with_business_plan, name="Security contacts")
        self._shoot(
            authenticated_page, snapshot, width, f"/workspaces/{team_with_business_plan.key}/settings/contact-profiles"
        )

    def test_workspace_settings_trust_center_snapshot(
        self, authenticated_page: Page, team_with_business_plan: Any, snapshot: Any, width: int
    ) -> None:
        team_with_business_plan.is_public = True
        team_with_business_plan.save(update_fields=["is_public"])
        self._shoot(
            authenticated_page, snapshot, width, f"/workspaces/{team_with_business_plan.key}/settings/trust-center"
        )


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
