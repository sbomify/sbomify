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


@pytest.mark.parametrize("template", TRIAGE_PANELS)
def test_a_triage_panel_refreshes_itself(template: str) -> None:
    source = _source(template)

    assert "triage-saved from:body" in source
    assert "vex-reapplied from:body" in source


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

    def test_the_fallback_poll_refreshes_the_results_region(self) -> None:
        source = _source("apps/sboms/templates/sboms/sbom_vulnerabilities.html.j2")

        assert 'hx-select="#scan-results-card"' in source
        assert "every 60s" in source
