"""The CISA KEV badge, from catalog lookup to rendered markup.

Every piece worked in isolation and the flag defaults to false, so the red badge
never appeared in any check: no fixture held a CVE that is actually in the
catalog. Log4Shell stands in here because it is a real KEV entry, and OSV
reports it as a GHSA id carrying the CVE as an alias, which is the shape the
alias branch exists for.

The catalog is a frozenset of lower-cased ids, built by ``kev_cve_ids`` from the
CISA feed. These tests pass one in directly, so nothing here touches the network.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.template.loader import render_to_string

from sbomify.apps.plugins.apis import _result_with_kev
from sbomify.apps.vulnerability_scanning.kev import finding_in_kev

LOG4SHELL = "CVE-2021-44228"
LOG4SHELL_GHSA = "GHSA-jfh8-c2jp-5v3q"
CATALOG = frozenset({LOG4SHELL.lower()})


def _finding(**overrides) -> dict:
    finding = {
        "id": LOG4SHELL,
        "title": "Remote code execution in log4j-core",
        "severity": "critical",
    }
    finding.update(overrides)
    return finding


def _security_run(findings: list[dict], category: str = "security") -> SimpleNamespace:
    """``_result_with_kev`` reads only ``result`` and ``category``."""
    return SimpleNamespace(
        category=category,
        result={
            "summary": {
                "total_findings": len(findings),
                "by_severity": {"critical": 1, "high": 0, "medium": 0, "low": 0, "info": 0, "unknown": 0},
            },
            "findings": findings,
        },
    )


class TestCatalogMatching:
    def test_a_listed_id_matches(self):
        assert finding_in_kev(_finding(), CATALOG) is True

    def test_a_listed_alias_matches(self):
        """OSV reports the GHSA id, so the CVE only appears under aliases."""
        finding = _finding(id=LOG4SHELL_GHSA, aliases=[LOG4SHELL])

        assert finding_in_kev(finding, CATALOG) is True

    def test_matching_ignores_case(self):
        assert finding_in_kev(_finding(id=LOG4SHELL.lower()), CATALOG) is True

    def test_an_unlisted_id_does_not_match(self):
        assert finding_in_kev(_finding(id="CVE-2026-99999"), CATALOG) is False

    def test_an_empty_catalog_matches_nothing(self):
        """A failed feed fetch caches an empty set, which must read as "no badge"
        rather than stamping everything or raising."""
        assert finding_in_kev(_finding(), frozenset()) is False


class TestResponseTimeStamp:
    def test_only_the_listed_finding_is_stamped(self):
        run = _security_run([_finding(), _finding(id="CVE-2026-99999", title="Something else")])

        findings = _result_with_kev(run, CATALOG)["findings"]

        assert findings[0]["kev"] is True
        assert "kev" not in findings[1]

    def test_the_stored_blob_is_left_alone(self):
        """The flag is response-time data from the cached feed, so the row keeps
        whatever the plugin wrote."""
        run = _security_run([_finding()])

        _result_with_kev(run, CATALOG)

        assert "kev" not in run.result["findings"][0]

    def test_a_non_security_run_passes_through(self):
        run = _security_run([_finding()], category="compliance")

        assert _result_with_kev(run, CATALOG) is run.result

    def test_an_empty_catalog_passes_through(self):
        run = _security_run([_finding()])

        assert _result_with_kev(run, frozenset()) is run.result


class TestBadgeMarkup:
    """The stamp is only worth anything if the template acts on it."""

    @staticmethod
    def _render(findings: list[dict]) -> str:
        run = _security_run(findings)
        return render_to_string(
            "plugins/components/_assessment_run_item.html.j2",
            {
                "run": {
                    "id": "run1",
                    "plugin_name": "osv",
                    "plugin_display_name": "OSV Vulnerability Scanner",
                    "plugin_version": "1.0.0",
                    "category": "security",
                    "status": "completed",
                    "run_reason": "on_upload",
                    "release_names": [],
                    "completed_at": None,
                    "result": run.result,
                },
                "loop_index": 1,
            },
        )

    def test_a_listed_finding_renders_the_badge(self):
        run = _security_run([_finding()])
        stamped = _result_with_kev(run, CATALOG)

        html = self._render(stamped["findings"])

        assert "Known Exploited Vulnerabilities catalog" in html

    def test_an_unlisted_finding_renders_no_badge(self):
        html = self._render([_finding(id="CVE-2026-99999")])

        assert "Known Exploited Vulnerabilities catalog" not in html
