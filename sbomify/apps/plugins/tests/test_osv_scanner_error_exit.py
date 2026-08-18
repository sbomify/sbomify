"""A scanner that aborted is not a scanner that found nothing.

From staging, four SBOMs in a single nightly sweep:

    [OSV] Scanner returned code 127: Starting filesystem walk for root: /
    [OSV] Completed scan for SBOM <id>: 0 vulnerabilities found

osv-scanner never completed the scan, so it wrote no JSON and no "found N
packages" line. ``_parse_scan_output`` saw empty stdout and returned no
findings; the no-packages guard reads the missing count as ``None`` rather
than ``0`` and so did not fire; and the plugin went on to publish a clean
result. An SBOM nothing had scanned was recorded as having no known
vulnerabilities.

The exit code is the only thing that separates the two cases, and it has to
be read before either of the empty-result heuristics downstream of it.
"""

from __future__ import annotations

import dataclasses
import subprocess
from typing import Any
from unittest.mock import patch

import pytest

from sbomify.apps.plugins.builtins.osv import OSVPlugin


def _as_dict(result: Any) -> dict[str, Any]:
    return result.model_dump() if hasattr(result, "model_dump") else dataclasses.asdict(result)


@pytest.fixture
def plugin() -> OSVPlugin:
    return OSVPlugin()


@pytest.fixture
def sbom_file(tmp_path):
    """A CycloneDX document already carrying the suffix the plugin wants, so
    ``assess`` does not take its temp-copy branch and the mock stays simple."""
    path = tmp_path / "scan.cdx.json"
    path.write_text('{"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []}')
    return path


def _scanner_exiting(returncode: int, stdout: str = "", stderr: str = "") -> Any:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestAnAbortedScanIsAnError:
    # 128 is deliberately absent: osv-scanner uses it for "no package sources
    # found", which is the scanner working and having nothing to match. It has
    # its own case below. The guard is written against "not a success code"
    # rather than against the specific values seen in the wild.
    @pytest.mark.parametrize("returncode", [2, 127, 255])
    def test_a_failing_exit_code_does_not_report_clean(self, plugin: OSVPlugin, sbom_file, returncode: int) -> None:
        """The defect itself: any exit outside {0, 1} used to fall through to a
        0-findings result that read as "no known vulnerabilities"."""
        with patch("subprocess.run", return_value=_scanner_exiting(returncode)):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert result["summary"]["error_count"] == 1
        assert result["findings"][0]["status"] == "error"

    def test_the_error_names_the_exit_code(self, plugin: OSVPlugin, sbom_file) -> None:
        """An operator seeing this has to be able to act on it, and the exit
        code is the only handle the scanner gave us."""
        with patch("subprocess.run", return_value=_scanner_exiting(127)):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert "127" in result["findings"][0]["description"]

    def test_stdout_from_a_failed_run_is_not_parsed(self, plugin: OSVPlugin, sbom_file) -> None:
        """A scanner that died mid-write can leave partial JSON on stdout.
        Whatever it contains describes an incomplete scan, so it must not
        become findings."""
        partial = '{"results": [{"packages": [{"package": {"name": "x"}, "vulnerabilities": ['
        with patch("subprocess.run", return_value=_scanner_exiting(2, stdout=partial)):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert result["summary"]["error_count"] == 1


class TestTheSuccessPathIsUntouched:
    """The regression that would hurt most: real scans have to keep working."""

    def test_a_clean_scan_still_reports_clean(self, plugin: OSVPlugin, sbom_file) -> None:
        clean = _scanner_exiting(0, stderr="Scanned /tmp/x.cdx.json file and found 412 packages\n")
        with patch("subprocess.run", return_value=clean):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert result["summary"]["error_count"] == 0
        assert result["summary"]["total_findings"] == 0

    def test_a_scan_that_found_vulnerabilities_still_reports_them(self, plugin: OSVPlugin, sbom_file) -> None:
        """Exit 1 means "vulnerabilities found", not failure."""
        output = (
            '{"results": [{"packages": [{"package": {"name": "lodash", "version": "4.17.15", '
            '"ecosystem": "npm"}, "vulnerabilities": [{"id": "GHSA-jf85-cpcp-j695", '
            '"summary": "Prototype pollution"}]}]}]}'
        )
        with patch("subprocess.run", return_value=_scanner_exiting(1, stdout=output)):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert result["summary"]["error_count"] == 0
        assert result["summary"]["total_findings"] == 1

    def test_exit_128_is_a_skip_not_an_error(self, plugin: OSVPlugin, sbom_file) -> None:
        """osv-scanner reserves 128 for "no package sources found". Staging
        bears out the semantics: every exit-128 run was followed by the
        no-packages skip firing on its stderr, while only exit 127 fell through
        to a clean result. Treating it as a failure turns a deliberate "Nothing
        scanned" into a high-severity Scan Error."""
        with patch("subprocess.run", return_value=_scanner_exiting(128)):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert result["metadata"]["skipped"] is True
        assert result["summary"]["error_count"] == 0

    def test_the_no_packages_skip_still_fires(self, plugin: OSVPlugin, sbom_file) -> None:
        """Exit 0 with nothing recognised stays a skip, not an error — the two
        guards answer different questions and both have to survive."""
        yocto = _scanner_exiting(0, stderr="Scanned /tmp/x.spdx.json file and found 0 packages\n")
        with patch("subprocess.run", return_value=yocto):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert result["metadata"]["skipped"] is True
        assert result["summary"]["error_count"] == 0


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

    def test_a_failed_scan_earns_no_public_badge(self, plugin: OSVPlugin, sbom_file) -> None:
        from sbomify.apps.plugins.public_assessment_utils import _is_run_passing

        with patch("subprocess.run", return_value=_scanner_exiting(127)):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert _is_run_passing(self._run(result)) is False


@pytest.mark.django_db
class TestItResolvesNothing:
    """The layer the original fix stopped short of.

    Withholding the badge was only half the problem: the run still reached the
    vulnerability lifecycle, which reads a completed run with no findings as
    evidence that everything previously open is now fixed.
    """

    def _run(self, result: dict[str, Any]):
        from sbomify.apps.plugins.models import AssessmentRun, RunStatus

        return AssessmentRun(
            plugin_name="osv",
            category="security",
            status=RunStatus.COMPLETED.value,
            result=result,
        )

    def test_a_failed_scan_is_not_treated_as_evidence(self, plugin: OSVPlugin, sbom_file) -> None:
        from sbomify.apps.plugins.lifecycle import run_scanned

        with patch("subprocess.run", return_value=_scanner_exiting(127)):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert run_scanned(self._run(result)) is False

    def test_a_clean_scan_still_is(self, plugin: OSVPlugin, sbom_file) -> None:
        """The regression that would hurt most: a real scan of a real SBOM with
        nothing wrong still has to resolve what it no longer reports."""
        from sbomify.apps.plugins.lifecycle import run_scanned

        clean = _scanner_exiting(0, stderr="Scanned /tmp/x.cdx.json file and found 412 packages\n")
        with patch("subprocess.run", return_value=clean):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert run_scanned(self._run(result)) is True


class TestTheSkipDoesNotPageAnyone:
    """settings wires Sentry to capture on ``logger.error``, so the level is
    not cosmetic: leaving 128 in the error branch raised an incident every hour
    for an SBOM the scanner simply had no packages to match."""

    def test_exit_128_is_not_logged_as_an_error(self, plugin: OSVPlugin, sbom_file) -> None:
        from sbomify.apps.plugins.builtins import osv as osv_module

        with (
            patch("subprocess.run", return_value=_scanner_exiting(128)),
            patch.object(osv_module.logger, "error") as error,
        ):
            plugin.assess("test-sbom", sbom_file)

        assert not [c for c in error.call_args_list if "Scanner" in c.args[0]]

    def test_a_genuine_failure_still_is(self, plugin: OSVPlugin, sbom_file) -> None:
        from sbomify.apps.plugins.builtins import osv as osv_module

        with (
            patch("subprocess.run", return_value=_scanner_exiting(127)),
            patch.object(osv_module.logger, "error") as error,
        ):
            plugin.assess("test-sbom", sbom_file)

        assert [c for c in error.call_args_list if "Scanner returned code" in c.args[0]]
