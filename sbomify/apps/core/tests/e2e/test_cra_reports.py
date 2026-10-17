"""CRA Article 14 reports: an owner records an early warning from the report page."""

import pytest
from django.utils import timezone as django_timezone
from playwright.sync_api import Page, expect

# Module scope for the same reason as test_cra_compliance.py: the compliance
# services pull in trestle, which cannot be imported once the clock is frozen.
from sbomify.apps.compliance.services import report_service  # noqa: E402
from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403


@pytest.mark.django_db
def test_an_owner_records_an_early_warning(
    authenticated_page: Page,
    product_factory,  # noqa: F405
    sample_user,  # noqa: F405
    team_with_business_plan,  # noqa: F405
) -> None:
    product = product_factory(name="Router OS", _id="crareportsos")
    result = report_service.create_report(
        team_with_business_plan,
        sample_user,
        kind="incident",
        product_id=product.id,
        aware_at=django_timezone.now(),
    )
    assert result.ok, result.error
    page = authenticated_page

    page.goto(f"/compliance/cra/reports/{result.value.id}/")
    expect(page.get_by_text("For the ENISA portal")).to_be_visible()
    page.get_by_label("ENISA reference").fill("SRP-2020-0001")
    page.get_by_role("button", name="Record filing").click()

    expect(page.get_by_text("Filing recorded.")).to_be_visible()
    expect(page.get_by_role("cell", name="SRP-2020-0001", exact=True)).to_be_visible()
