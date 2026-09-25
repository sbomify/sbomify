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
from django.template.loader import render_to_string

TEMPLATES = Path(__file__).resolve().parents[3]

#: Every template on this surface that used to reload the page.
NO_RELOAD = [
    "apps/plugins/templates/plugins/components/triage_modal.html.j2",
    "apps/plugins/templates/plugins/components/assessment_results_card.html.j2",
    "apps/sboms/templates/sboms/sbom_vulnerabilities.html.j2",
]

#: Panels that host a triage control and so must refresh once the decision is
#: recorded, and again when the background re-apply reports in.
TRIAGE_PANELS = [
    "apps/core/templates/core/components/component_vulnerabilities_table.html.j2",
    "apps/sboms/templates/sboms/components/scan_vulnerabilities.html.j2",
    "apps/plugins/templates/plugins/components/_assessment_run_findings.html.j2",
]


def _source(relative: str) -> str:
    return (TEMPLATES / relative).read_text()


@pytest.mark.parametrize("template", NO_RELOAD)
def test_the_surface_never_reloads_the_page(template: str) -> None:
    assert "location.reload" not in _source(template)


@pytest.mark.parametrize("template", TRIAGE_PANELS)
def test_a_triage_panel_refreshes_itself(template: str) -> None:
    source = _source(template)

    assert "triage-saved from:body" in source
    assert "vex-reapplied from:body" in source


@pytest.mark.parametrize("template", TRIAGE_PANELS)
def test_a_refresh_keeps_the_reader_in_place(template: str) -> None:
    """morph preserves scroll position and focus; outerHTML does not."""
    assert 'hx-swap="morph"' in _source(template)


class TestTriageModal:
    def test_saving_announces_the_decision_rather_than_reloading(self) -> None:
        html = render_to_string(
            "plugins/components/triage_modal.html.j2",
            {"component_id": "comp1", "team_key": "ws1"},
        )

        assert "triage-saved" in html
        assert "location.reload" not in html

    def test_it_relays_the_re_apply_broadcast_to_the_panels(self) -> None:
        """The panels cannot listen to the socket themselves: each is swapped
        out by its own filters, which would drop the listener."""
        html = render_to_string(
            "plugins/components/triage_modal.html.j2",
            {"component_id": "comp1", "team_key": "ws1"},
        )

        assert "vex_reapplied" in html
        assert "vex-reapplied" in html


class TestAssessmentCard:
    def _render(self) -> str:
        return render_to_string(
            "plugins/components/assessment_results_card.html.j2",
            {
                "sbom_id": "sbom1",
                "assessment_runs": {"status_summary": {"total_assessments": 0}, "latest_runs": []},
            },
        )

    def test_a_finishing_assessment_refreshes_only_its_own_section(self) -> None:
        html = self._render()

        assert 'hx-select="#assessment-results"' in html
        assert 'hx-trigger="assessment-complete from:body"' in html
        assert "location.reload" not in html

    def test_the_refresh_keeps_the_reader_in_place(self) -> None:
        assert 'hx-swap="morph"' in self._render()

    def test_it_does_not_lend_its_target_to_the_cards_inside_it(self) -> None:
        """htmx inherits hx-target, hx-select and hx-swap down the tree.

        Each run card fetches its findings from a descendant that sets neither
        target nor select. Without hx-disinherit those requests went through
        this element's hx-select, matched nothing in the findings response, and
        emptied the whole assessments section the moment a reader opened a card.
        """
        assert 'hx-disinherit="*"' in self._render()


class TestScanProcessingState:
    def test_it_no_longer_reloads_on_a_timer(self) -> None:
        """A 300 second reload fired whether or not anything had changed."""
        source = _source("apps/sboms/templates/sboms/sbom_vulnerabilities.html.j2")

        assert "setTimeout" not in source
        assert "location.reload" not in source

    def test_the_fallback_poll_refreshes_the_results_region(self) -> None:
        source = _source("apps/sboms/templates/sboms/sbom_vulnerabilities.html.j2")

        assert 'hx-select="#scan-results-card"' in source
        assert "every 60s" in source
