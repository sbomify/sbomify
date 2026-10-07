"""The security surfaces refresh a region; they do not reload the page.

Recording a triage decision, or an assessment finishing, used to call
``location.reload()``. A reload arrives unannounced and takes everything the
reader had built up with it: a triage modal with a justification half typed, a
suppression search, an expanded disclosure, the open assessment card and the
filters and page inside it. The reload after a triage save was also timed
against ``reapply_vex_to_component_scans``, a background task that broadcast
nothing, so the page it rebuilt usually still showed the pre-triage state.

These tests hold each surface to refreshing its own region instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[3]

#: Every template on this surface that used to reload the page.
NO_RELOAD = [
    "apps/plugins/templates/plugins/components/triage_modal.html.j2",
    "apps/plugins/templates/plugins/components/assessment_results_card.html.j2",
    "apps/sboms/templates/sboms/sbom_vulnerabilities.html.j2",
]

#: Panels that host a triage control and so must refresh once the decision is
#: recorded, and again when the background re-apply reports in.
#:
#: The assessment card's findings panel is not one of them. The artifact page
#: refreshes as a whole region and marks that panel hx-preserve, because the
#: server always renders it unopened: refetching it on triage would take back
#: the filters the reader had set, which is the loss the region refresh exists
#: to prevent.
TRIAGE_PANELS = [
    "apps/core/templates/core/components/component_vulnerabilities_table.html.j2",
    "apps/sboms/templates/sboms/components/scan_vulnerabilities.html.j2",
]


def _source(relative: str) -> str:
    return (TEMPLATES / relative).read_text()


@pytest.mark.parametrize("template", NO_RELOAD)
def test_the_surface_never_reloads_the_page(template: str) -> None:
    assert "location.reload" not in _source(template)


def _root_attributes(html: str, element_id: str) -> dict[str, str]:
    """The attributes of the element with ``element_id``, as a browser reads them.

    Parsed rather than matched: the socket bridge holds an arrow function, and
    its ``>`` ends any pattern that stops at the end of the tag.
    """
    from html.parser import HTMLParser

    found: dict[str, str] = {}

    class Root(HTMLParser):
        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if not found and dict(attrs).get("id") == element_id:
                found.update((name, value or "") for name, value in attrs)

    Root().feed(html)
    return found


@pytest.mark.django_db
class TestATriagePanelRefreshesWhereTheReaderIs:
    """Each triage panel refreshes on the events this flow emits, on the reader's page.

    The triage modal dispatches ``refresh-assessments`` when a decision is
    saved, and the background re-apply arrives as a ``ws:message`` of type
    ``vex_reapplied``. Nothing emits any other event, so a panel listening for
    one never refreshes. The pager's links reset to page one, so the refresh
    carries its own query, page included.
    """

    def test_the_component_panel(self, sample_team_with_owner_member, sample_user) -> None:
        from django.test import Client
        from django.urls import reverse

        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
        from sbomify.apps.core.tests.test_panel_triage_and_page_size import _component_with_findings

        team = sample_team_with_owner_member.team
        component = _component_with_findings(team)
        client = Client()
        setup_authenticated_client_session(client, team, sample_user)

        response = client.get(
            reverse("core:component_vulnerabilities_panel", args=[component.id]),
            {"vuln_submitted": "1", "vuln_page": "2"},
            headers={"hx-request": "true"},
        )

        root = _root_attributes(response.content.decode(), "component-vulnerabilities-table")
        assert "vuln_page=2" in root["hx-get"]
        assert root["hx-trigger"] == "refresh-assessments from:body"
        assert "'vex_reapplied'" in root["@ws:message.window"]
        assert f"'{component.id}'" in root["@ws:message.window"]

    def test_the_artifact_report(self, sample_team_with_owner_member, sample_user) -> None:
        from django.test import Client
        from django.urls import reverse

        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
        from sbomify.apps.core.tests.test_panel_triage_and_page_size import _component_with_findings
        from sbomify.apps.sboms.models import SBOM

        team = sample_team_with_owner_member.team
        component = _component_with_findings(team)
        sbom = SBOM.objects.get(component=component)
        client = Client()
        setup_authenticated_client_session(client, team, sample_user)

        response = client.get(
            reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sbom.id}),
            {"scan_submitted": "1", "scan_page": "2"},
        )

        root = _root_attributes(response.content.decode(), "scan-vulnerabilities")
        assert "scan_page=2" in root["hx-get"]
        assert root["hx-trigger"] == "refresh-assessments from:body"
        assert "'vex_reapplied'" in root["@ws:message.window"]
        assert f"'{component.id}'" in root["@ws:message.window"]


@pytest.mark.parametrize("template", TRIAGE_PANELS)
def test_a_refresh_keeps_the_reader_in_place(template: str) -> None:
    """morph preserves scroll position and focus; outerHTML does not."""
    assert 'hx-swap="morph"' in _source(template)


# The triage modal and the assessment card are covered by the artifact page's
# own region-refresh tests: the browser checks that an open, filtered panel and
# a half-written justification survive a refresh, and a unit spec covers the
# morph that preserves them.


class TestScanProcessingState:
    def test_it_no_longer_reloads_on_a_timer(self) -> None:
        """A 300 second reload fired whether or not anything had changed."""
        source = _source("apps/sboms/templates/sboms/sbom_vulnerabilities.html.j2")

        assert "setTimeout" not in source
        assert "location.reload" not in source

    # There was a test here for the 60s fallback poll refreshing
    # #scan-results-card. It is gone because the thing it asserted is gone:
    # the processing branch it lived in was unreachable, and #1781 removed the
    # branch and its poll together. Nothing on this page now renders a
    # processing state, so there is no interval to fall back to -- a finished
    # scan renders the results table instead. The sibling test above still
    # pins the part that matters, that no timer reloads the page.
