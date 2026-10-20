"""The verdict on one assessment's row.

A plugin that could not run returns ``metadata={"skipped": True}``. The API
layer honours that through ``_is_run_skipped``; these tests hold the row to
the same reading, because a skipped run rendered as "Warnings only" reads as a
scanner that ran and disagreed with the others.
"""

from __future__ import annotations

import pytest
from django.template.loader import render_to_string

# The row's verdict takes its ink from its tone; this is the warning recipe, and
# its absence is what "not a warning" means.
WARNING_INK = "text-warning"


def _run(**overrides) -> dict:
    run = {
        "id": "run1",
        "plugin_name": "dependency-track",
        "plugin_display_name": "Dependency Track",
        "plugin_version": "1.0.0",
        "category": "security",
        "status": "completed",
        "run_reason": "on_upload",
        "release_names": [],
        "completed_at": None,
        "result": {
            "summary": {
                "total_findings": 1,
                "pass_count": 0,
                "fail_count": 0,
                "warning_count": 1,
                "error_count": 0,
            },
            "findings": [
                {
                    "id": "dependency-track:unsupported-format",
                    "title": "Format Not Supported",
                    "description": "Dependency Track only supports CycloneDX format.",
                    "status": "warning",
                    "severity": "info",
                }
            ],
            "metadata": {},
        },
    }
    run.update(overrides)
    return run


def _card(*runs: dict, **context) -> str:
    """The assessments card as the artifact page renders it.

    Compliance runs are listed as rows in its sources list. Vulnerability scans
    are not rows here: the page links to the Vulnerabilities list instead.
    """
    return render_to_string(
        "plugins/components/assessment_results_card.html.j2",
        {
            "assessment_runs": {
                "status_summary": {"overall_status": "", "total_assessments": len(runs)},
                "latest_runs": list(runs),
                "requirements": {"columns": [], "sources": list(runs), "met": 0},
            },
            **context,
        },
    )


def _render(run: dict) -> str:
    """The run's own row in the card, so the card's heading badge cannot answer for it."""
    html = _card(run)
    start = html.index(f'id="plugin-{run["plugin_name"]}"')
    return html[start : html.index("</li>", start)]


def _findings_of(run: dict) -> str:
    """The list the card fetches once a reader opens it.

    The card itself carries a placeholder and an hx-get; the rows live in their
    own partial, which is what these assertions are about.
    """
    from sbomify.apps.plugins.templatetags.plugins_extras import vulnerability_findings

    findings = run["result"]["findings"]
    is_security = run.get("category") == "security"
    return render_to_string(
        "plugins/components/_assessment_run_findings.html.j2",
        {
            "run": run,
            "is_security": is_security,
            "findings": vulnerability_findings(findings) if is_security else findings,
            "vex_statements": [],
            "can_triage": True,
            "page": 1,
            "page_count": 1,
            "has_prev": False,
            "has_next": False,
        },
    )


def _compliance_run(**overrides) -> dict:
    """The row's subject: the card lists compliance runs, not scans."""
    return _run(plugin_name="pqc", plugin_display_name="Post-Quantum Readiness", category="compliance", **overrides)


class TestSkippedRunBadge:
    def test_skipped_run_reads_as_skipped(self):
        """A plugin that never ran on the artifact: "Warnings only" is a lie."""
        run = _compliance_run()
        run["result"]["metadata"] = {"skipped": True}

        html = _render(run)

        assert "Skipped" in html
        assert "Warnings only" not in html

    def test_skipped_run_names_the_reason_without_expanding(self):
        """A finding count says nothing about why the plugin stood down."""
        run = _compliance_run()
        run["result"]["metadata"] = {"skipped": True}

        html = _render(run)

        assert "Format Not Supported" in html
        assert "1 findings" not in html

    def test_skipped_run_is_not_coloured_as_a_warning(self):
        run = _compliance_run()
        run["result"]["metadata"] = {"skipped": True}

        assert WARNING_INK not in _render(run)

    def test_a_skipped_compliance_run_names_its_own_reason(self):
        """PQC skips a document with no crypto assets."""
        run = _compliance_run()
        run["result"]["metadata"] = {"skipped": True}
        run["result"]["findings"] = [
            {
                "id": "pqc:no-assets",
                "title": "No cryptographic assets found",
                "description": "This document declares no crypto-asset components; nothing to assess.",
                "status": "info",
                "severity": "info",
            }
        ]

        html = _render(run)

        assert "Skipped" in html
        assert "Warnings only" not in html
        assert "No cryptographic assets found" in html

    def test_a_real_warnings_only_run_is_untouched(self):
        """A plugin that ran and produced only warnings still reads that way."""
        html = _render(_compliance_run())

        assert "Warnings only" in html
        assert "Skipped" not in html

    def test_a_run_with_no_result_still_renders(self):
        """Pending and running rows carry result=None, so the verdict must not
        reach into it for the skipped flag."""
        html = _render(_compliance_run(status="running", result=None))

        assert "Running" in html
        assert "Skipped" not in html

    def test_a_passing_run_is_untouched(self):
        run = _compliance_run()
        run["result"]["summary"] = {
            "total_findings": 3,
            "pass_count": 3,
            "fail_count": 0,
            "warning_count": 0,
            "error_count": 0,
        }

        html = _render(run)

        assert "Passed" in html
        assert "Skipped" not in html

    def test_a_failing_run_is_untouched(self):
        run = _compliance_run()
        run["result"]["summary"] = {
            "total_findings": 2,
            "pass_count": 0,
            "fail_count": 2,
            "warning_count": 0,
            "error_count": 0,
        }

        html = _render(run)

        assert "2 issues" in html
        assert "Skipped" not in html


class TestStatusMarkersAreNotVulnerabilities:
    """The status marker a skipped scanner leaves in the findings array
    explains the run; it is not a vulnerability. It must not appear in the
    vulnerabilities list or grow a Triage button."""

    def _skipped_security_run(self) -> dict:
        run = _run()
        run["result"]["metadata"] = {"skipped": True}
        run["result"]["findings"] = [
            {
                "id": "dependency-track:no-product",
                "title": "Skipped — component has no product membership",
                "description": "Dependency Track scanning requires product membership.",
                "status": "info",
                "severity": "info",
            }
        ]
        return run

    def test_marker_does_not_render_as_a_vulnerability_row(self):
        html = _findings_of(self._skipped_security_run())
        assert "findings-list" not in html
        assert "Triage" not in html

    def test_real_findings_still_render(self):
        run = _run()
        run["result"]["findings"] = [
            {
                "id": "CVE-2025-1111",
                "title": "A real vulnerability",
                "severity": "high",
                "component": {"name": "django", "version": "5.2.3"},
            }
        ]
        html = _findings_of(run)
        assert "CVE-2025-1111" in html
        assert 'aria-label="Vulnerabilities"' in html


def test_a_vulnerability_scan_is_offered_no_rerun():
    """The plan and the backend schedule decide when a scan repeats, so even a
    caller allowed to re-run the artifact's other assessments is not handed one."""
    scan = _run()
    standard = _compliance_run()

    html = _card(scan, standard, sbom_id="sbom1", can_rerun=True)

    assert "/sbom1/pqc/rerun" in html
    assert "/dependency-track/rerun" not in html
    assert 'id="plugin-dependency-track"' not in html


@pytest.mark.parametrize(
    ("status", "label"), [("failed", "Could not run"), ("pending", "Queued"), ("running", "Running")]
)
def test_an_unfinished_vulnerability_scan_still_shows_its_state(status, label):
    """The Vulnerabilities list has nothing from a scan that has not finished, so the card keeps its row."""
    from django.template.loader import render_to_string

    run = {
        "id": "r1",
        "plugin_name": "osv",
        "plugin_display_name": "OSV",
        "category": "security",
        "status": status,
        "error_message": "Scanner timed out" if status == "failed" else None,
        "result": None,
    }
    html = render_to_string(
        "plugins/components/assessment_results_card.html.j2",
        {
            "assessment_runs": {
                "latest_runs": [run],
                "status_summary": {"total_assessments": 1, "overall_status": status},
                "requirements": {"columns": [], "sources": []},
                "unassessed_plugins": [],
            },
            "sbom_id": "s1",
        },
    )
    assert label in html
    if status == "failed":
        assert "Scanner timed out" in html


def test_a_completed_scan_that_errored_still_shows_its_state():
    """Scanner errors are stored as completed runs; the list has nothing from them, so the card keeps the row."""
    from django.template.loader import render_to_string

    run = {
        "id": "r1",
        "plugin_name": "osv",
        "plugin_display_name": "OSV",
        "category": "security",
        "status": "completed",
        "result": {"summary": {"error_count": 1}, "findings": []},
    }
    html = render_to_string(
        "plugins/components/assessment_results_card.html.j2",
        {
            "assessment_runs": {
                "latest_runs": [run],
                "status_summary": {"total_assessments": 1, "overall_status": "has_failures"},
                "requirements": {"columns": [], "sources": []},
                "unassessed_plugins": [],
            },
            "sbom_id": "s1",
        },
    )
    assert "Could not scan" in html


def test_a_completed_scan_error_shows_what_the_scanner_said():
    """The scanner's diagnostic is the only place the reason survives, so the row shows it."""
    from sbomify.apps.plugins.services.assessment_scorecard import scorecard_for_run

    marker = {"id": "osv:scan-error", "status": "error", "title": "Scan Error", "description": "OSV timed out"}
    run = {"category": "security", "status": "completed", "result": {"summary": {"error_count": 1}, "findings": [marker]}}
    assert scorecard_for_run(run)["caption"] == "OSV timed out"

    run["result"]["findings"] = []
    assert scorecard_for_run(run)["caption"] == "The scanner reported an error."
