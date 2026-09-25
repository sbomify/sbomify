"""The per-run assessment card badge.

A plugin that could not run returns ``metadata={"skipped": True}``. The API
layer honours that through ``_is_run_skipped``; these tests hold the template to
the same reading, because a skipped run rendered as "Warnings Only" reads as a
scanner that ran and disagreed with the others.
"""

from __future__ import annotations

from django.template.loader import render_to_string

# The card takes its border from c-cards.collapsible's level; this is the recipe
# that level="warning" emits, and its absence is what "not a warning" means now
# that the card carries no tw-collapsible-card--warning class.
WARNING_BORDER = "border-[color-mix(in_oklab,var(--color-warning)_30%,transparent)]"


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
    return render_to_string("plugins/components/_assessment_run_item.html.j2", {"run": run, "loop_index": 1})


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
    """What a reader sees before expanding the card.

    The findings list lives inside ``x-show="expanded"``, so asserting against
    the whole render would pass on text nobody can see.
    """
    return _render(run).split('x-show="expanded"')[0]


class TestSkippedRunBadge:
    def test_skipped_run_reads_as_skipped(self):
        """DT on an SPDX SBOM: it never scanned, so "Warnings Only" is a lie."""
        run = _run()
        run["result"]["metadata"] = {"skipped": True}

        html = _render(run)

        assert "Skipped" in html
        assert "Warnings Only" not in html

    def test_skipped_run_names_the_reason_without_expanding(self):
        """A finding count says nothing about why the plugin stood down, and the
        finding that explains it stays hidden until the card is expanded."""
        run = _run()
        run["result"]["metadata"] = {"skipped": True}

        header = _header(run)

        assert "Format Not Supported" in header
        assert "1 findings" not in header

    def test_skipped_run_is_not_coloured_as_a_warning(self):
        run = _run()
        run["result"]["metadata"] = {"skipped": True}

        html = _render(run)

        assert WARNING_BORDER not in html

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
        assert "Warnings Only" not in header
        assert "No cryptographic assets found" in header

    def test_a_real_warnings_only_run_is_untouched(self):
        """A plugin that ran and produced only warnings still reads that way."""
        html = _render(_run())

        assert "Warnings Only" in html
        assert "Skipped" not in html

    def test_a_run_with_no_result_still_renders(self):
        """Pending and running rows carry result=None, which is why the template
        aliases it before the skipped lookup."""
        html = _render(_run(status="running", result=None))

        assert "Running" in html
        assert "Skipped" not in html

    def test_a_passing_run_is_untouched(self):
        run = _run()
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
        run = _run()
        run["result"]["summary"] = {
            "total_findings": 2,
            "pass_count": 0,
            "fail_count": 2,
            "warning_count": 0,
            "error_count": 0,
        }

        html = _render(run)

        assert "2 Issues" in html
        assert "Skipped" not in html


def _security_run(**overrides) -> dict:
    """A security run as the plugins actually emit it, with ``by_severity``.

    ``_run`` omits it, which sends every case above through the compliance
    branch. Dependency Track fills it in even when it skips (one ``info``), so
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

        assert WARNING_BORDER not in _render(run)

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

    def test_skipped_total_renders_zero(self):
        import re

        html = _render(self._skipped_security_run())
        total_value = re.search(r"<dt\b[^>]*>\s*Total\s*</dt>\s*<dd\b[^>]*>\s*(\d+)\b", html)
        assert total_value, "Total stat card not found"
        # The stored summary says 1 (the marker); the card must say 0.
        assert total_value.group(1) == "0"

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
        assert "findings-list" in html


class TestUnreadableResultBadge:
    """A run whose stored result failed schema validation.

    ``_run_to_schema`` drops a result blob that does not validate to ``None`` so
    one bad row cannot blank the whole page. Every count is then zero, which used
    to fall through to "Warnings Only", a verdict the run never gave. A security
    run carrying a critical finding read as warnings-only.
    """

    def test_a_run_without_a_result_does_not_claim_a_verdict(self):
        html = _render(_run(result=None))

        assert "Result unavailable" in html
        assert "Warnings Only" not in html
        assert "Passed" not in html

    def test_it_is_not_coloured_as_a_warning(self):
        """No verdict is not a warning, so the card keeps the neutral border."""
        assert WARNING_BORDER not in _render(_run(result=None))

    def test_a_real_warnings_only_run_still_reads_as_one(self):
        """The guard above must not swallow the state it sits in front of."""
        html = _render(_run(category="compliance"))

        assert "Warnings Only" in html
        assert "Result unavailable" not in html


class TestBadgeCarriesItsVerdict:
    """Every status used one neutral badge, so "issues found" and "all passed"
    were the same grey and severity survived only as a border tint."""

    def test_a_clean_security_run_is_a_success_badge(self):
        # by_severity must be present for the card to read the run as a security
        # run at all; a clean scan reports the buckets and zero in each.
        run = _run()
        run["result"]["summary"]["by_severity"] = {"critical": 0, "high": 0}
        run["result"]["findings"] = []

        assert "No vulnerabilities" in _render(run)

    def test_a_security_run_with_findings_is_a_warning_badge(self):
        run = _run()
        run["result"]["summary"]["by_severity"] = {"critical": 1}

        html = _render(run)

        assert "1 vulnerability" in html

    def test_a_failed_run_is_a_danger_badge(self):
        """An errored run and a passing one must not render the same badge."""
        danger = _render(_run(status="failed", category="compliance"))
        success = _render(_run(status="completed", category="compliance", result=_passing_result()))

        assert "Error" in danger
        assert "Passed" in success
        # The two badges differ in more than their text.
        assert _badge_classes(danger) != _badge_classes(success)


def _passing_result() -> dict:
    return {
        "summary": {
            "total_findings": 1,
            "pass_count": 1,
            "fail_count": 0,
            "warning_count": 0,
            "error_count": 0,
        },
        "findings": [
            {"id": "c1", "title": "A check", "description": "It passed.", "status": "pass"}
        ],
        "metadata": {},
    }


def _badge_classes(html: str) -> set[str]:
    """Every class the header's badges carry, so a colour change is observable."""
    import re

    header = html.split('x-show="expanded"')[0]
    return {c for m in re.findall(r'class="([^"]*)"', header) for c in m.split()}
