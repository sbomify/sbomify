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

import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[3]

#: Every template on this surface that used to reload the page.
NO_RELOAD = [
    "apps/plugins/templates/plugins/components/triage_modal.html.j2",
    "apps/plugins/templates/plugins/components/assessment_results_card.html.j2",
    "apps/core/templates/core/components/component_vulnerabilities_table.html.j2",
    "templates/components/vulnerabilities/workspace_results.html",
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
    """The component panel refreshes on the events this flow emits, on the reader's page.

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
            {"page": "2", "per_page": "10"},
            headers={"hx-request": "true"},
        )
        html = response.content.decode()

        # The re-apply bridge sits on the region, and names this component.
        root = _root_attributes(html, "component-vulnerabilities-table")
        assert "'vex_reapplied'" in root["@ws:message.window"]
        assert "refresh-assessments" in root["@ws:message.window"]
        assert f"'{component.id}'" in root["@ws:message.window"]
        # The results refresh themselves on that event, at the page the reader is on.
        results = _root_attributes(html, "component-vulnerabilities-results")
        assert results["hx-trigger"] == "refresh-assessments from:body"
        assert "page=2" in results["hx-get"]
        assert "per_page=10" in results["hx-get"]
        assert results["hx-get"].startswith(reverse("core:component_vulnerabilities_panel", args=[component.id]))


# The triage modal and the assessment card are covered by the artifact page's
# own region-refresh tests: the browser checks that an open, filtered panel and
# a half-written justification survive a refresh, and a unit spec covers the
# morph that preserves them.


class TestScanProcessingState:
    @pytest.mark.parametrize("template", NO_RELOAD)
    def test_it_no_longer_refreshes_on_a_timer(self, template: str) -> None:
        """A 300 second reload fired whether or not anything had changed.

        A short debounce after a scan's completion message is not that: it waits
        for something that did change. What must not come back is a refresh
        nothing asked for, whether a reload, an interval or an htmx poll.
        """
        source = _source(template)

        assert "location.reload" not in source
        assert "setInterval" not in source
        assert not re.search(r'hx-trigger="[^"]*\bevery\b', source)
