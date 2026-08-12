import pytest
from django.utils import timezone
from playwright.sync_api import Page

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.security_advisories.models import SecurityAdvisory


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
