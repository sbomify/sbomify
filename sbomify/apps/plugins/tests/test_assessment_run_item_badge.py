"""The verdict on one assessment's row.

A plugin that could not run returns ``metadata={"skipped": True}``. The API
layer honours that through ``_is_run_skipped``; these tests hold the row to
the same reading, because a skipped run rendered as "Warnings only" reads as a
scanner that ran and disagreed with the others.
"""

from __future__ import annotations

from django.template.loader import render_to_string

from sbomify.apps.plugins.services.assessment_scorecard import scorecard_for_run

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


def _render(run: dict) -> str:
    """The row as the page renders it: the run beside the verdict computed for it."""
    return render_to_string(
        "plugins/components/_assessment_run_item.html.j2", {"run": run, "tile": scorecard_for_run(run)}
    )


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
            "can_triage": True,
            "page": 1,
            "page_count": 1,
            "has_prev": False,
            "has_next": False,
        },
    )


def _header(run: dict) -> str:
    """What a reader sees before opening the row.

    The findings live in the collapsed details, so asserting against the whole
    render would pass on text nobody can see.
    """
    return _render(run).split("x-collapse")[0]


class TestSkippedRunBadge:
    def test_skipped_run_reads_as_skipped(self):
        """DT on an SPDX SBOM: it never scanned, so "Warnings only" is a lie."""
        run = _run()
        run["result"]["metadata"] = {"skipped": True}

        html = _render(run)

        assert "Skipped" in html
        assert "Warnings only" not in html

    def test_skipped_run_names_the_reason_without_expanding(self):
        """A finding count says nothing about why the plugin stood down, and the
        finding that explains it stays hidden until the row is opened."""
        run = _run()
        run["result"]["metadata"] = {"skipped": True}

        header = _header(run)

        assert "Format Not Supported" in header
        assert "1 findings" not in header

    def test_skipped_run_is_not_coloured_as_a_warning(self):
        run = _run()
        run["result"]["metadata"] = {"skipped": True}

        assert WARNING_INK not in _header(run)

    def test_a_skipped_compliance_run_reads_the_same(self):
        """PQC skips a document with no crypto assets. Different category, same
        rendering branch, so it was mislabelled the same way."""
        run = _run(
            plugin_name="pqc",
            plugin_display_name="Post-Quantum Readiness",
            category="compliance",
        )
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

        header = _header(run)

        assert "Skipped" in header
        assert "Warnings only" not in header
        assert "No cryptographic assets found" in header

    def test_a_real_warnings_only_run_is_untouched(self):
        """A plugin that ran and produced only warnings still reads that way."""
        html = _render(_run(category="compliance"))

        assert "Warnings only" in html
        assert "Skipped" not in html

    def test_a_run_with_no_result_still_renders(self):
        """Pending and running rows carry result=None, so the verdict must not
        reach into it for the skipped flag."""
        html = _render(_run(status="running", result=None))

        assert "Running" in html
        assert "Skipped" not in html

    def test_a_passing_run_is_untouched(self):
        run = _run(category="compliance")
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
        run = _run(category="compliance")
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


def _security_run(**overrides) -> dict:
    """A security run as the plugins actually emit it, with ``by_severity``.

    ``_run`` omits it. The verdict is chosen by category, so the passing,
    failing and warnings-only cases above say compliance outright. Dependency Track fills it in even when it skips (one ``info``), so
    the card renders through the security branch instead, and that is the path
    that called the skip "1 Vulnerability".
    """
    run = _run(**overrides)
    run["result"]["summary"]["by_severity"] = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "info": 1,
        "unknown": 0,
    }
    return run


class TestSkippedSecurityRunBadge:
    """Same rule, security branch: DT handed an SPDX SBOM scanned nothing."""

    def test_skipped_run_reads_as_skipped_not_as_a_vulnerability(self):
        run = _security_run()
        run["result"]["metadata"] = {"skipped": True}

        header = _header(run)

        assert "Skipped" in header
        assert "Vulnerabilit" not in header

    def test_skipped_run_names_the_reason_without_expanding(self):
        run = _security_run()
        run["result"]["metadata"] = {"skipped": True}

        header = _header(run)

        assert "Format Not Supported" in header
        assert "1 findings" not in header

    def test_skipped_run_is_not_coloured_as_a_warning(self):
        run = _security_run()
        run["result"]["metadata"] = {"skipped": True}

        assert WARNING_INK not in _header(run)

    def test_a_real_scan_is_untouched(self):
        """The case beside it on the same page: OSV reporting real findings."""
        run = _security_run(plugin_name="osv", plugin_display_name="OSV Vulnerability Scanner")
        run["result"]["summary"]["total_findings"] = 117
        run["result"]["summary"]["by_severity"] = {
            "critical": 7,
            "high": 32,
            "medium": 23,
            "low": 55,
            "info": 0,
            "unknown": 0,
        }

        header = _header(run)

        assert "117 vulnerabilities" in header
        assert "Skipped" not in header

    def test_a_clean_scan_is_untouched(self):
        run = _security_run()
        run["result"]["summary"]["total_findings"] = 0
        run["result"]["summary"]["by_severity"] = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "info": 0,
            "unknown": 0,
        }

        header = _header(run)

        assert "No vulnerabilities" in header
        assert "Skipped" not in header


class TestStatusMarkersAreNotVulnerabilities:
    """The status marker a skipped scanner leaves in the findings array
    explains the run; it is not a vulnerability. It must not appear in the
    vulnerabilities list, grow a Triage button, or count in the Total card."""

    def _skipped_security_run(self) -> dict:
        run = _security_run()
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

    def test_the_marker_is_not_counted_as_a_vulnerability(self):
        # The stored summary counts 1 (the marker) in by_severity; the row
        # must count none, draw no bar and write no breakdown.
        run = self._skipped_security_run()
        tile = scorecard_for_run(run)
        header = _header(run)

        assert tile["segments"] == []
        assert 'role="img"' not in header
        assert "1 vulnerability" not in header

    def test_real_findings_still_render(self):
        run = _security_run()
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
