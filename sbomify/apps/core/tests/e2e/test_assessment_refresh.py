"""Refreshing the assessments section must not destroy it.

The artifact page refreshes its content region with hx-select against the page
response when an assessment completes, and the section has to survive that
morph. Vulnerability scans are not listed in the section, so it is seeded with
compliance runs: with scans alone the section is not rendered at all.
"""

import pytest
from playwright.sync_api import Page, expect

from sbomify.apps.core.tests.e2e.fixtures import *  # noqa: F403
from sbomify.apps.core.tests.e2e.test_assessment_requirements import _seed


def _section_size(page: Page) -> int:
    return page.evaluate("() => (document.querySelector('#assessment-results') || {}).innerHTML?.length || 0")


@pytest.mark.django_db
class TestAssessmentSectionRefresh:
    def test_a_completing_assessment_re_renders_the_section(
        self,
        authenticated_page: Page,
        sbom_component_details,  # noqa: F811
        mocker,
    ) -> None:
        """The socket's assessment_complete drives a region refresh, which keeps the section.

        Sent the way the socket store sends it, and waited on through the
        region's own settle: an event nothing listens for would leave the first
        render in place and pass without any refresh having run.
        """
        from django.urls import reverse

        from sbomify.apps.sboms.models import SBOM

        mocker.patch("sbomify.apps.core.object_store.StorageClient.get_sbom_data", return_value=None)
        sbom = SBOM.objects.get(component=sbom_component_details)
        _seed(sbom)
        page = authenticated_page
        page.goto(reverse("core:component_item", args=[sbom.component_id, "sboms", sbom.id]))
        page.wait_for_load_state("networkidle")

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
