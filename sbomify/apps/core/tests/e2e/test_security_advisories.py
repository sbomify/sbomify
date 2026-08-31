import pytest
from django.utils import timezone
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.security_advisories.models import SecurityAdvisory
from sbomify.apps.security_advisories.services.advisories import create_advisory


@pytest.fixture
def advisories(team_with_business_plan):  # noqa: F811
    """Twelve advisories across the statuses, so the list shows every status
    badge, both publication states and a second page for the pager."""
    statuses = [
        SecurityAdvisory.Status.DRAFT,
        SecurityAdvisory.Status.PUBLISHED,
        SecurityAdvisory.Status.WITHDRAWN,
    ]
    published_at = timezone.now()
    created = []
    for i in range(12):
        status = statuses[i % len(statuses)]
        # A published or withdrawn advisory has been published once, so the
        # model requires the stamp and the tracking id.
        extra: dict = {}
        if status != SecurityAdvisory.Status.DRAFT:
            extra = {"published_at": published_at, "tracking_id": f"ACME-SA-2026-{i:04d}"}
        if status == SecurityAdvisory.Status.WITHDRAWN:
            # Withdrawal carries its own stamp and reason.
            extra |= {"withdrawn_at": published_at, "withdrawal_reason": "Superseded by a later advisory."}
        created.append(
            SecurityAdvisory.objects.create(
                team=team_with_business_plan,
                title=f"Advisory {i:02d} in Acme Gateway",
                status=status,
                **extra,
            )
        )
    # The e2e suite freezes the clock, so auto_now_add stamps all twelve rows
    # with the same instant and the list's -created_at ordering becomes a
    # twelve-way tie postgres breaks arbitrarily. The snapshot then only
    # matches its baseline when the arbitrary order happens to repeat.
    # Distinct timestamps make the render deterministic: Advisory 11 first.
    # Set on the instances and bulk-updated, so a test reading created_at off
    # the fixture sees the same value the database holds.
    for i, advisory in enumerate(created):
        advisory.created_at = published_at - timezone.timedelta(minutes=len(created) - i)
    SecurityAdvisory.objects.bulk_update(created, ["created_at"])
    yield created


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestSecurityAdvisoriesListSnapshot:
    def test_security_advisories_list_snapshot(
        self,
        authenticated_page: Page,
        advisories,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/security-advisories/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.fixture
def advisory_detail(team_with_business_plan, sample_user, product_factory):  # noqa: F811
    """One advisory carrying everything the detail page renders: a severity, a
    description, a CVE, an affected product and an opening timeline entry."""
    product = product_factory("Acme Gateway")
    result = create_advisory(
        team_with_business_plan,
        sample_user,
        title="Path traversal in the Acme Gateway upload handler",
        severity="high",
        description=(
            "A crafted upload path escapes the storage directory and can overwrite files "
            "the service can write to. Only deployments with uploads enabled are affected."
        ),
        identifier="CVE-2026-0001",
        remediation_status="investigating",
        cvss_score=8.6,
        cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N",
        products=[product],
    )
    yield SecurityAdvisory.objects.get(id=result.value)


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestSecurityAdvisoryDetailSnapshot:
    """One advisory: the clamped header, the timeline with its composer and the
    details sidebar with the affected product and the reference list."""

    def test_security_advisory_detail_snapshot(
        self,
        authenticated_page: Page,
        advisory_detail,
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto(f"/security-advisories/{advisory_detail.id}/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())


@pytest.mark.django_db
@pytest.mark.parametrize("width", [1920, 992, 576, 375])
class TestSecurityAdvisoryNewSnapshot:
    """The new advisory form. The product_details fixture gives the affected
    products picker a product with three versions, so both panes have rows."""

    def test_security_advisory_new_snapshot(
        self,
        authenticated_page: Page,
        product_details,  # noqa: F811
        snapshot,
        width: int,
    ) -> None:
        authenticated_page.goto("/security-advisories/new/")
        authenticated_page.wait_for_load_state("networkidle")

        baseline = snapshot.get_or_create_baseline_screenshot(authenticated_page, width=width)
        current = snapshot.take_screenshot(authenticated_page, width=width)

        snapshot.assert_screenshot(baseline.as_posix(), current.as_posix())
