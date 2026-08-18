import pytest
from playwright.sync_api import Page

from sbomify.apps.core.models import Release
from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestReleasesListSnapshot:
    """The releases list. The product_details fixture gives it a latest
    release, a pre-release and a plain one, so the row badges are covered."""

    def test_releases_list_snapshot(
        self,
        authenticated_page: Page,
        product_details,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/releases/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestReleaseDetailsSnapshot:
    """One release, seen by the workspace that owns it. This is where the
    artifacts panel lives: its toolbar, its sortable table and the empty state
    it falls back to. The public twin is covered in test_public_pages.py."""

    def test_release_details_snapshot(
        self,
        authenticated_page: Page,
        product_details,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        release = Release.objects.get(product=product_details, name="v1.0.0")

        authenticated_page.goto(f"/product/{product_details.id}/release/{release.id}/")
        authenticated_page.wait_for_load_state("networkidle")
        # The artifacts panel loads over the API and raises a toast when that
        # call fails. Toasts expire after three seconds, so let them go before
        # the first capture or the two screenshots disagree about them.
        authenticated_page.wait_for_timeout(4000)

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
