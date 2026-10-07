"""Refreshing the assessments section must not destroy it.

The section refreshes itself with hx-select against the page response. htmx
inherits hx-target, hx-select and hx-swap down the tree, and each run card
fetches its findings from a descendant that sets neither target nor select, so
without hx-disinherit those requests ran through the section's own hx-select,
matched nothing, and emptied the section the moment a reader opened a card.
"""

import pytest
from playwright.sync_api import Page, expect

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.core.tests.e2e.test_sbom_vulnerabilities import sbom_with_findings  # noqa: F401


def _section_size(page: Page) -> int:
    return page.evaluate("() => (document.querySelector('#assessment-results') || {}).innerHTML?.length || 0")


@pytest.mark.django_db
class TestAssessmentSectionRefresh:
    def _open(self, page: Page, sbom) -> None:
        from django.urls import reverse

        page.goto(reverse("core:component_item", args=[sbom.component_id, "sboms", sbom.id]))
        page.wait_for_load_state("networkidle")

    def test_opening_a_run_card_keeps_the_section(self, authenticated_page: Page, sbom_with_findings) -> None:  # noqa: F811
        from sbomify.apps.plugins.models import AssessmentRun

        sbom = sbom_with_findings
        run = AssessmentRun.objects.get(sbom=sbom, plugin_name="dependency_track")
        page = authenticated_page
        self._open(page, sbom)
        before = _section_size(page)

        page.locator(f"#run-trigger-{run.id}").click()
        expect(page.locator(f"#findings-{run.id}")).to_be_visible()

        # The findings arrived inside the section rather than in place of it.
        assert _section_size(page) > before

    def test_a_completing_assessment_re_renders_the_section(self, authenticated_page: Page, sbom_with_findings) -> None:  # noqa: F811
        """The socket's assessment_complete drives a region refresh, which keeps the section.

        Sent the way the socket store sends it, and waited on through the
        region's own settle: an event nothing listens for would leave the first
        render in place and pass without any refresh having run.
        """
        page = authenticated_page
        sbom = sbom_with_findings
        self._open(page, sbom)

        page.evaluate(
            """(sbomId) => {
                window.__regionSettled = false;
                document.body.addEventListener('htmx:afterSettle', (event) => {
                    if (event.target.id === 'artifact-content') window.__regionSettled = true;
                });
                window.dispatchEvent(new CustomEvent('ws:message', {
                    detail: { type: 'assessment_complete', sbom_id: sbomId },
                }));
            }""",
            str(sbom.id),
        )
        page.wait_for_function("window.__regionSettled === true")

        expect(page.locator("#assessment-results")).to_be_visible()
        expect(page.locator("#assessment-results").get_by_text("Assessments", exact=True)).to_be_visible()
        assert _section_size(page) > 0


@pytest.mark.django_db(transaction=True)
def test_a_finished_scan_reaches_a_report_opened_before_it(authenticated_page: Page, sbom_with_findings) -> None:  # noqa: F811
    """The report used to reload itself on a timer. Now the scan's own completion message refreshes it."""
    from django.urls import reverse

    from sbomify.apps.plugins.models import AssessmentRun

    sbom = sbom_with_findings
    AssessmentRun.objects.filter(sbom=sbom).update(status="running")
    page = authenticated_page
    page.goto(reverse("sboms:sbom_vulnerabilities", args=[sbom.id]))
    expect(page.get_by_text("No Scan Data Available")).to_be_visible()

    def _complete(sbom_id: str) -> None:
        page.evaluate(
            """(sbomId) => window.dispatchEvent(new CustomEvent('ws:message', {
                detail: { type: 'assessment_complete', sbom_id: sbomId },
            }))""",
            sbom_id,
        )

    # Another SBOM's scan schedules nothing here. The bridge runs while the
    # message dispatches, so its debounce state answers at once.
    _complete("some-other-sbom-id")
    assert page.locator("#scan-report").evaluate("(el) => window.Alpine.$data(el).refreshTimer") is None

    AssessmentRun.objects.filter(sbom=sbom).update(status="completed")
    _complete(str(sbom.id))

    expect(page.get_by_text("No Scan Data Available")).to_have_count(0)
    expect(page.locator("#scan-vulnerabilities")).to_be_visible()
