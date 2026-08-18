"""Snapshot coverage for the workspace plugins page.

The page had no e2e referee, so it is added here before its templates move to
the component library: the baseline captures the render as it is today. The
page loads both of its panels over HTMX (the summary bar and the settings
form), so the wait is on the settings form rather than on load alone.
"""

import pytest
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestPluginsPageSnapshot:
    """The plugins page: the summary bar, the per-category plugin rows with
    their toggles, version and artifact-type badges, the plan-gated rows and
    the per-plugin config fields."""

    def test_plugins_page_snapshot(
        self,
        authenticated_page: Page,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/plugins/")
        authenticated_page.wait_for_load_state("networkidle")
        authenticated_page.wait_for_selector("#plugin-settings-form")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
