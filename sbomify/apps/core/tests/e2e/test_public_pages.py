"""Snapshot coverage for the public product, release and workspace pages.

test_products.py and test_components.py already referee the public product
details and public component pages. These four had no referee at all, so they
gained one here before the component-library migration touched them.
"""

import pytest
from playwright.sync_api import Page, expect

from sbomify.apps.core.models import LATEST_RELEASE_NAME, Component
from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.security_advisories.services.advisories import create_advisory, publish_advisory


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestWorkspacePublicSnapshot:
    def test_workspace_public_snapshot(
        self,
        authenticated_page: Page,
        trust_center_product,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/public/workspace/{trust_center_product.team.key}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestProductReleasesPublicSnapshot:
    def test_product_releases_public_snapshot(
        self,
        authenticated_page: Page,
        trust_center_product,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/public/product/{trust_center_product.id}/releases/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestReleaseDetailsPublicSnapshot:
    def test_release_details_public_snapshot(
        self,
        authenticated_page: Page,
        trust_center_product,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        # A real versioned release, not the synthetic auto-managed `latest`.
        release = trust_center_product.releases.exclude(name=LATEST_RELEASE_NAME).filter(is_prerelease=False).first()

        authenticated_page.goto(f"/public/product/{trust_center_product.id}/release/{release.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_release_details_public_prerelease_snapshot(
        self,
        authenticated_page: Page,
        trust_center_product,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        # The pre-release badge in the masthead only renders on this branch.
        release = trust_center_product.releases.filter(is_prerelease=True).first()

        authenticated_page.goto(f"/public/product/{trust_center_product.id}/release/{release.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestComponentItemPublicSnapshot:
    def test_component_item_public_sbom_snapshot(
        self,
        authenticated_page: Page,
        trust_center_product,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        component = trust_center_product.components.filter(component_type=Component.ComponentType.BOM).first()
        sbom = component.sbom_set.first()

        authenticated_page.goto(f"/public/components/{component.id}/sboms/{sbom.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.fixture
def public_advisory(trust_center_product, sample_user):  # noqa: F811
    """One published advisory on the trust-center product, carrying what both
    public advisory pages render: a severity and CVSS score, a CVE, a
    description, an affected product and a timeline."""
    team = trust_center_product.team
    created = create_advisory(
        team,
        sample_user,
        title="Path traversal in the Backend API upload handler",
        severity="high",
        description=(
            "A crafted upload path escapes the storage directory and can overwrite files "
            "the service can write to. Only deployments with uploads enabled are affected."
        ),
        identifier="CVE-2026-0001",
        remediation_status="investigating",
        cvss_score=8.6,
        cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N",
        products=[trust_center_product],
    )
    assert created.ok, created.error
    published = publish_advisory(team, sample_user, created.value, visibility="public")
    assert published.ok, published.error
    yield created.value


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 375])
def test_many_affected_versions_fold_in_the_public_table(
    authenticated_page: Page,
    trust_center_product,  # noqa: F811
    sample_user,  # noqa: F811
    width: int,
) -> None:
    """The "Am I affected?" table lists each affected version on its own line
    and folds past five, so a long list does not stretch the row."""
    from sbomify.apps.core.models import Release

    team = trust_center_product.team
    releases = [
        Release.objects.create(product=trust_center_product, name=f"v9.{n}.0", version=f"9.{n}.0") for n in range(12)
    ]
    created = create_advisory(
        team,
        sample_user,
        title="Many affected versions",
        identifier="CVE-2026-0002",
        products=[trust_center_product],
        affected_releases=releases,
    )
    assert created.ok, created.error
    assert publish_advisory(team, sample_user, created.value, visibility="public").ok

    page = authenticated_page
    page.set_viewport_size({"width": width, "height": 1080})
    page.goto(f"/public/workspace/{team.key}/advisories/{created.value}/")

    versions = page.get_by_role("list", name=f"Affected versions of {trust_center_product.name} for CVE-2026-0002")
    items = versions.locator("li")
    expect(items).to_have_count(12)
    expect(items.first).to_have_text("9.0.0")
    expect(items.nth(4)).to_be_visible()
    expect(items.nth(5)).to_be_hidden()

    page.get_by_text("Show all 12").click()
    expect(items.nth(11)).to_be_visible()


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestTrustCenterAdvisoriesPublicSnapshot:
    def test_trust_center_advisories_public_snapshot(
        self,
        authenticated_page: Page,
        trust_center_product,  # noqa: F811
        public_advisory,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/public/workspace/{trust_center_product.team.key}/advisories/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())

    def test_trust_center_advisory_detail_public_snapshot(
        self,
        authenticated_page: Page,
        trust_center_product,  # noqa: F811
        public_advisory,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/public/workspace/{trust_center_product.team.key}/advisories/{public_advisory}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
def test_advisory_filters_open_from_the_toggle_on_a_phone(
    authenticated_page: Page,
    trust_center_product,  # noqa: F811
    public_advisory,
) -> None:
    """The narrow-screen filter panel is a disclosure driven by a checkbox in
    the page shell, through selectors that name it. Collapsed on load, opened
    by its label, and still open after a facet swaps the region beneath it."""
    page = authenticated_page
    page.set_viewport_size({"width": 375, "height": 900})
    page.goto(f"/public/workspace/{trust_center_product.team.key}/advisories/")
    page.wait_for_load_state("networkidle")

    body = page.locator("#advisoryFilterBody")
    expect(body).to_be_hidden()
    page.locator("label[for=tcFiltersOpen]").click()
    expect(body).to_be_visible()

    body.get_by_text("High", exact=True).click()
    page.wait_for_load_state("networkidle")
    expect(page.locator("#advisoryFilterBody")).to_be_visible()
    expect(page.locator("#advisoryFilterBody input[name=severity][value=high]")).to_be_checked()
