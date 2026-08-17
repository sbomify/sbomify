"""A scan that recognised nothing is not a scan that found nothing.

From staging, on a Yocto SPDX document:

    Invalid PURL "pkg:yocto/netbase@6.4" for package: "netbase"
    Neither CPE nor PURL found for package: ...
    Scanned /tmp/tmpi1fa3vpf.spdx.json file and found 0 packages

osv-scanner rejected every PURL, matched the document against nothing, and
exited cleanly. The plugin built its result from the findings alone, so zero
findings became a pass, and the component rendered a green "no known
vulnerabilities" badge over a build that was never checked.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from sbomify.apps.plugins.builtins.osv import OSVPlugin


def _as_dict(result: Any) -> dict[str, Any]:
    return result.model_dump() if hasattr(result, "model_dump") else dataclasses.asdict(result)


@pytest.fixture
def plugin() -> OSVPlugin:
    return OSVPlugin()


# The line osv-scanner actually writes, from the staging log.
YOCTO_STDERR = (
    'Invalid PURL "pkg:yocto/netbase@6.4" for package: "netbase"\n'
    "Neither CPE nor PURL found for package: &{IsUnpackaged:false PackageName:netbase}\n"
    "Scanned /tmp/tmpi1fa3vpf.spdx.json file and found 0 packages\n"
)
HEALTHY_STDERR = "Scanned /tmp/x.spdx.json file and found 412 packages\n"


class TestReadingTheScannedCount:
    def test_zero_is_read_from_the_real_line(self, plugin: OSVPlugin) -> None:
        assert plugin._scanned_package_count(YOCTO_STDERR) == 0

    def test_a_healthy_scan_reports_its_count(self, plugin: OSVPlugin) -> None:
        assert plugin._scanned_package_count(HEALTHY_STDERR) == 412

    def test_a_missing_line_is_not_zero(self, plugin: OSVPlugin) -> None:
        """None, not 0. A scanner version that words it differently must not
        turn every clean scan into a skip — that would be the same defect
        pointing the other way."""
        assert plugin._scanned_package_count("") is None
        assert plugin._scanned_package_count("some unrelated warning") is None

    def test_the_singular_form_is_read_too(self, plugin: OSVPlugin) -> None:
        assert plugin._scanned_package_count("Scanned x and found 1 package\n") == 1


class TestTheResultItProduces:
    def test_it_is_marked_skipped(self, plugin: OSVPlugin) -> None:
        """``skipped`` is what withholds the public pass. ``_is_run_skipped``
        reads exactly this flag, and its docstring is this situation: the
        plugin never scanned anything, so "no findings" carries no signal."""
        result = _as_dict(plugin._create_no_packages_result())

        assert result["metadata"]["skipped"] is True

    def test_it_asserts_no_severity(self, plugin: OSVPlugin) -> None:
        """It must not read as a vulnerability either — the row would be as
        wrong as the badge."""
        summary = _as_dict(plugin._create_no_packages_result())["summary"]

        assert summary["by_severity"] is None
        assert summary["fail_count"] == 0
        assert summary["error_count"] == 0
        assert summary["warning_count"] == 1

    def test_its_finding_is_operational_not_a_vulnerability(self, plugin: OSVPlugin) -> None:
        """The id shares the ``osv:`` namespace the display filter already
        drops, so it cannot surface as a finding row."""
        from sbomify.apps.vulnerability_scanning.utils import is_vulnerability

        finding = _as_dict(plugin._create_no_packages_result())["findings"][0]

        assert finding["id"] == "osv:no-packages"
        assert is_vulnerability(finding) is False

    def test_it_says_why(self, plugin: OSVPlugin) -> None:
        """An operator seeing this has to be able to act on it, and the cause
        is a PURL type the scanner does not know."""
        finding = _as_dict(plugin._create_no_packages_result())["findings"][0]

        assert "pkg:yocto" in finding["description"]


@pytest.mark.django_db
class TestItDoesNotRenderAsPassing:
    """The point of the whole change."""

    def _run(self, result: dict[str, Any]):
        from sbomify.apps.plugins.models import AssessmentRun, RunStatus

        return AssessmentRun(
            plugin_name="osv",
            category="security",
            status=RunStatus.COMPLETED.value,
            result=result,
        )

    def test_a_no_packages_run_earns_no_public_badge(self, plugin: OSVPlugin) -> None:
        from sbomify.apps.plugins.public_assessment_utils import _is_run_passing

        assert _is_run_passing(self._run(_as_dict(plugin._create_no_packages_result()))) is False

    def test_a_genuinely_clean_run_still_does(self) -> None:
        """The regression that would hurt most: a real scan of a real SBOM with
        no vulnerabilities has to keep its badge."""
        from sbomify.apps.plugins.public_assessment_utils import _is_run_passing

        clean = {
            "summary": {
                "total_findings": 0,
                "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0, "unknown": 0},
            },
            "findings": [],
            "metadata": {"scanner": "osv-scanner"},
        }

        assert _is_run_passing(self._run(clean)) is True
