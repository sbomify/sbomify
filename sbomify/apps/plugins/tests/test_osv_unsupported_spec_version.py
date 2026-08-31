"""osv-scanner refusing a CycloneDX version is a gap, not a fault.

The bundled binary only reads the spec versions it shipped knowing about, so a
CycloneDX 1.7 document comes back as:

    Error during extraction: (extracting as sbom/cdx) <file>: invalid specification version
    extraction failed on specified lockfile
    exit=127

The scan did not fail. The scanner is older than the spec, the artifact is
valid, and a later osv-scanner reads it with nobody intervening. Reported as an
error it became a high-severity Scan Error on a good SBOM, restated on every
scheduled rescan.

Dependency Track hits the identical wall on the identical documents and already
answers with a skip. The two now agree, and both build the answer with the same
SDK helper.

Exit 127 alone is not the signal: it is also the conventional shell code for
"command not found", so the stderr wording is what separates the two.
"""

from __future__ import annotations

import dataclasses
import subprocess
from typing import Any
from unittest.mock import patch

import pytest

from sbomify.apps.plugins.builtins.osv import OSVPlugin, _is_unsupported_spec_version

# What osv-scanner actually wrote, from the issue's reproduction.
REAL_REJECTION = (
    "Error during extraction: (extracting as sbom/cdx) /tmp/scan.cdx.json: invalid specification version\n"
    "extraction failed on specified lockfile\n"
)


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
    path.write_text('{"bomFormat": "CycloneDX", "specVersion": "1.7", "components": []}')
    return path


def _scanner_exiting(returncode: int, stdout: str = "", stderr: str = "") -> Any:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestRecognisingTheRejection:
    def test_the_real_message_is_recognised(self) -> None:
        assert _is_unsupported_spec_version(REAL_REJECTION) is True

    @pytest.mark.parametrize(
        "stderr",
        [
            "Error during extraction: unsupported SPDX version SPDX-3.0",
            "unsupported specVersion 2.0",
            "INVALID SPECIFICATION VERSION",
        ],
    )
    def test_wording_variants_are_recognised(self, stderr: str) -> None:
        assert _is_unsupported_spec_version(stderr) is True

    @pytest.mark.parametrize(
        "stderr",
        [
            # 127 is also "command not found", which is a genuine failure.
            "osv-scanner: command not found",
            # A genuinely broken document, which must keep its error result.
            "Error during extraction: unexpected end of JSON input",
            "failed to resolve https://api.osv.dev: connection refused",
            "",
        ],
    )
    def test_other_failures_are_not_swallowed(self, stderr: str) -> None:
        """The narrowness is the point. Reading a corrupt document or a missing
        binary as "not applicable" would hide the thing worth knowing."""
        assert _is_unsupported_spec_version(stderr) is False


class TestTheResultItProduces:
    @pytest.fixture
    def result(self, plugin: OSVPlugin) -> dict[str, Any]:
        return _as_dict(plugin._create_unsupported_spec_version_result())

    def test_it_is_skipped_not_errored(self, result: dict[str, Any]) -> None:
        assert result["metadata"]["skipped"] is True
        assert result["summary"]["error_count"] == 0

    def test_it_carries_no_severity(self, result: dict[str, Any]) -> None:
        """The error result it replaces carried ``severity="high"``, which is
        what put a HIGH row on the component page."""
        assert result["findings"][0]["severity"] != "high"

    def test_it_is_not_a_vulnerability(self, result: dict[str, Any]) -> None:
        from sbomify.apps.vulnerability_scanning.utils import is_vulnerability

        assert is_vulnerability(result["findings"][0]) is False

    def test_it_counts_towards_nothing(self, result: dict[str, Any]) -> None:
        """The marker rides the findings array, so every surface that totals
        findings has to read zero for it."""
        from sbomify.apps.vulnerability_scanning.utils import extract_severity_counts

        assert result["summary"]["total_findings"] == 0
        assert extract_severity_counts(result)["total"] == 0

    def test_it_names_the_plugin_it_came_from(self, result: dict[str, Any]) -> None:
        """The SDK helper reads identity from ``get_metadata()``. A helper that
        hardcoded the wrong slug would store a run attributed to Dependency
        Track."""
        assert result["plugin_name"] == "osv"

    def test_it_says_why(self, result: dict[str, Any]) -> None:
        """A reader seeing this has to know the SBOM is fine and that the
        scanner will catch up."""
        description = result["findings"][0]["description"]

        assert "spec version" in description
        assert "Nothing is wrong with the SBOM" in description

    def test_it_does_not_quote_the_scanner_at_the_reader(self, plugin: OSVPlugin, sbom_file) -> None:
        """Raw stderr names the orchestrator's temp path and runs to whatever
        length the scanner felt like. It belongs in the log line, which already
        has it, not in copy."""
        with patch("subprocess.run", return_value=_scanner_exiting(127, stderr=REAL_REJECTION)):
            described = _as_dict(plugin.assess("test-sbom", sbom_file))["findings"][0]["description"]

        assert "/tmp/" not in described
        assert "extraction failed" not in described


class TestTheWiringInAssess:
    """The branch itself, not just the pieces it is built from."""

    def test_the_real_rejection_becomes_a_skip(self, plugin: OSVPlugin, sbom_file) -> None:
        with patch("subprocess.run", return_value=_scanner_exiting(127, stderr=REAL_REJECTION)):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert result["metadata"]["skipped"] is True
        assert result["findings"][0]["id"] == "osv:unsupported-spec-version"
        assert result["summary"]["error_count"] == 0

    def test_the_rejection_carries_the_backoff_marker(self, plugin: OSVPlugin, sbom_file) -> None:
        """Asserted on the real assess() path rather than only against the
        helper. The scheduled sweep reads this flag off the stored run and the
        two live in different modules, so dropping it from this call site would
        leave the suite green while every rejection lost the marker and the
        hourly rescan loop came back."""
        with patch("subprocess.run", return_value=_scanner_exiting(127, stderr=REAL_REJECTION)):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert result["metadata"]["unsupported_input"] is True

    def test_a_bare_127_is_still_an_error(self, plugin: OSVPlugin, sbom_file) -> None:
        """The half that keeps the change honest. 127 with nothing on stderr is
        a missing binary, not a spec version."""
        with patch("subprocess.run", return_value=_scanner_exiting(127)):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert result["metadata"].get("skipped") is not True
        assert result["findings"][0]["id"] == "osv:error"
        assert result["summary"]["error_count"] == 1

    def test_a_missing_binary_is_still_an_error(self, plugin: OSVPlugin, sbom_file) -> None:
        with patch("subprocess.run", return_value=_scanner_exiting(127, stderr="osv-scanner: command not found")):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert result["summary"]["error_count"] == 1

    def test_a_clean_scan_is_untouched(self, plugin: OSVPlugin, sbom_file) -> None:
        """The regression that would hurt most: real scans have to keep working."""
        clean = _scanner_exiting(0, stderr="Scanned /tmp/x.cdx.json file and found 412 packages\n")
        with patch("subprocess.run", return_value=clean):
            result = _as_dict(plugin.assess("test-sbom", sbom_file))

        assert result["metadata"].get("skipped") is not True
        assert result["summary"]["error_count"] == 0
        assert result["summary"]["total_findings"] == 0


@pytest.mark.django_db
class TestWhatTheRunMeansDownstream:
    def _run(self, result: dict[str, Any]):
        from sbomify.apps.plugins.models import AssessmentRun, RunStatus

        return AssessmentRun(
            plugin_name="osv",
            category="security",
            status=RunStatus.COMPLETED.value,
            result=result,
        )

    @pytest.fixture
    def result(self, plugin: OSVPlugin, sbom_file) -> dict[str, Any]:
        with patch("subprocess.run", return_value=_scanner_exiting(127, stderr=REAL_REJECTION)):
            return _as_dict(plugin.assess("test-sbom", sbom_file))

    def test_it_earns_no_public_badge(self, result: dict[str, Any]) -> None:
        """Not an error, but not a clean bill of health either — nothing was
        scanned."""
        from sbomify.apps.plugins.public_assessment_utils import _is_run_passing

        assert _is_run_passing(self._run(result)) is False

    def test_it_resolves_nothing(self, result: dict[str, Any]) -> None:
        """A run that examined nothing is not evidence that anything previously
        open is now fixed."""
        from sbomify.apps.plugins.lifecycle import run_scanned

        assert run_scanned(self._run(result)) is False


@pytest.mark.django_db
class TestEveryNonScanPathSaysSo:
    """The invariant behind the whole change, asserted across all of them.

    OSV has three ways to return without osv-scanner having examined anything,
    and they were added one at a time, each learning the lesson separately. The
    SPDX 3.0 path never did: it carried ``unsupported_format`` in its metadata,
    which nothing reads, and omitted ``skipped``, which everything reads. So an
    SPDX 3.0 upload earned a green "no known vulnerabilities" badge and, worse,
    ``lifecycle.run_scanned`` took its empty findings array as evidence and
    resolved everything a previous real scan had found.

    Parametrised rather than written out three times, so a fourth non-scan path
    added later is one line away from being covered and cannot quietly ship
    without the marker.
    """

    NON_SCAN_PATHS = ("_create_no_packages_result", "_create_unsupported_format_result")

    def _run(self, result: dict[str, Any]):
        from sbomify.apps.plugins.models import AssessmentRun, RunStatus

        return AssessmentRun(
            plugin_name="osv",
            category="security",
            status=RunStatus.COMPLETED.value,
            result=result,
        )

    def _results(self, plugin: OSVPlugin) -> list[dict[str, Any]]:
        built = [_as_dict(getattr(plugin, name)()) for name in self.NON_SCAN_PATHS]
        return [*built, _as_dict(plugin._create_unsupported_spec_version_result())]

    def test_they_are_all_marked_skipped(self, plugin: OSVPlugin) -> None:
        assert [r["metadata"].get("skipped") for r in self._results(plugin)] == [True, True, True]

    def test_none_of_them_earns_a_public_badge(self, plugin: OSVPlugin) -> None:
        from sbomify.apps.plugins.public_assessment_utils import _is_run_passing

        assert [_is_run_passing(self._run(r)) for r in self._results(plugin)] == [False, False, False]

    def test_none_of_them_resolves_anything(self, plugin: OSVPlugin) -> None:
        from sbomify.apps.plugins.lifecycle import run_scanned

        assert [run_scanned(self._run(r)) for r in self._results(plugin)] == [False, False, False]

    def test_none_of_them_counts_towards_a_severity_total(self, plugin: OSVPlugin) -> None:
        from sbomify.apps.vulnerability_scanning.utils import extract_severity_counts

        assert [extract_severity_counts(r)["total"] for r in self._results(plugin)] == [0, 0, 0]


class TestTheSkipDoesNotPageAnyone:
    """settings wires Sentry to capture on ``logger.error``, so the level is not
    cosmetic: an error line here raises an incident every sweep because
    CycloneDX shipped a new version."""

    def test_the_rejection_is_not_logged_as_an_error(self, plugin: OSVPlugin, sbom_file) -> None:
        from sbomify.apps.plugins.builtins import osv as osv_module

        with (
            patch("subprocess.run", return_value=_scanner_exiting(127, stderr=REAL_REJECTION)),
            patch.object(osv_module.logger, "error") as error,
        ):
            plugin.assess("test-sbom", sbom_file)

        assert error.call_args_list == []

    def test_a_genuine_failure_still_is(self, plugin: OSVPlugin, sbom_file) -> None:
        from sbomify.apps.plugins.builtins import osv as osv_module

        with (
            patch("subprocess.run", return_value=_scanner_exiting(127, stderr="osv-scanner: command not found")),
            patch.object(osv_module.logger, "error") as error,
        ):
            plugin.assess("test-sbom", sbom_file)

        assert [c for c in error.call_args_list if "Scanner returned code" in c.args[0]]
