"""The dialogs and partials no page snapshot can see.

The add-workspace form modal and the delete confirmation modal are rendered
hidden on the pages that carry them, and the trusted-publishers section only
exists once its modal has fetched it, so a full-page baseline never captures
any of the three. These cases open them first and shoot the result.
"""

from typing import Any, Generator

import pytest
from playwright.sync_api import Browser, Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.core.tests.e2e.utils import BROWSER_HEIGHT, BROWSER_WIDTH


@pytest.fixture
def anonymous_page(browser: Browser, browser_base_url: str) -> Generator[Page, Any, None]:
    """A page with no session cookie, for the pages only a logged-out visitor
    reaches."""
    context = browser.new_context(
        base_url=browser_base_url,
        viewport={"width": BROWSER_WIDTH, "height": BROWSER_HEIGHT},
        device_scale_factor=1,
        reduced_motion="reduce",
    )
    page_instance = context.new_page()
    yield page_instance
    page_instance.close()
    context.close()


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 576])
class TestWorkspaceModalsSnapshot:
    """The two shared modal partials, opened from the workspace dashboard: the
    form modal that adds a workspace and the delete confirmation."""

    def test_add_workspace_modal_snapshot(
        self,
        authenticated_page: Page,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/workspaces/")
        authenticated_page.wait_for_load_state("networkidle")
        authenticated_page.get_by_role("button", name="Add workspace").click()
        authenticated_page.wait_for_selector("#add-workspace-modal-dialog-title")
        authenticated_page.wait_for_timeout(500)

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_delete_workspace_modal_snapshot(
        self,
        authenticated_page: Page,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/workspaces/")
        authenticated_page.wait_for_load_state("networkidle")
        # The row's delete control only renders for a workspace that is not the
        # member's default, and the fixture's only workspace is. Raise the event
        # that control raises, with the payload it carries.
        authenticated_page.evaluate(
            "window.dispatchEvent(new CustomEvent('open-delete-workspace-modal', "
            "{ detail: { formData: { key: 'e2e-key' }, displayName: 'Test Business Team' } }))"
        )
        authenticated_page.wait_for_selector("#delete-workspace-modal-label")
        authenticated_page.wait_for_timeout(500)

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 576])
class TestTrustedPublishersSnapshot:
    """The trusted-publishers section inside its modal: the bindings table,
    the add form and the workflow snippet."""

    def test_trusted_publishers_snapshot(
        self,
        authenticated_page: Page,
        sbom_component_details,
        snapshot,
        width: int,
    ) -> None:
        from sbomify.apps.oidc.models import OIDCBinding

        OIDCBinding.objects.create(
            component_id=sbom_component_details.id,
            repository="sbomify/example-app",
            repository_id=123456,
            repository_owner_id=654321,
        )
        OIDCBinding.objects.create(
            component_id=sbom_component_details.id,
            repository="sbomify/private-app",
        )

        authenticated_page.goto(f"/component/{sbom_component_details.id}/")
        authenticated_page.wait_for_load_state("networkidle")
        authenticated_page.evaluate("window.dispatchEvent(new CustomEvent('open-trusted-publishers'))")
        authenticated_page.wait_for_selector("#trusted-publishers-section")
        authenticated_page.wait_for_timeout(1000)

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 576])
class TestAuthenticationErrorSnapshot:
    """The sign-in error page. It only renders for a visitor who is not signed
    in: an authenticated one is sent to the dashboard instead."""

    def test_authentication_error_snapshot(
        self,
        anonymous_page: Page,
        snapshot,
        width: int,
    ) -> None:
        anonymous_page.goto("/login_error?error=invalid_grant&error_description=The+authorization+code+has+expired")
        anonymous_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(anonymous_page, width=width)
        current = snapshot.take_screenshot(anonymous_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
