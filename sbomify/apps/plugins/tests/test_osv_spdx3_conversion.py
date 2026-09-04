"""SPDX 3 reaches the scanner through a derived copy rather than a shrug.

osv-scanner has no SPDX 3 reader, so these documents used to come back as a
skip telling the uploader to convert the file themselves. The scan path now
does that conversion, scans the copy, and reports the findings against the
stored artifact, which is never touched (ADR-004).

The two skips that remain are the honest ones: a deployment with no converter
installed, and a document no converter will read.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sbomify.apps.plugins.builtins.osv import OSVPlugin
from sbomify.apps.sboms.conversion import ConversionFailed, ConversionUnavailable

SPDX3 = json.dumps({"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": []})
CONVERTED = b'{"spdxVersion": "SPDX-2.3", "packages": []}'
CLEAN_SCAN = ('{"results": []}', "", 0)


def _as_dict(result: Any) -> dict[str, Any]:
    return result.model_dump() if hasattr(result, "model_dump") else dataclasses.asdict(result)


@pytest.fixture
def plugin() -> OSVPlugin:
    return OSVPlugin()


@pytest.fixture
def spdx3_file(tmp_path: Path) -> Path:
    path = tmp_path / "scan.json"
    path.write_text(SPDX3)
    return path


class TestTheScannerReadsTheDerivedCopy:
    def test_the_converted_bytes_are_what_gets_scanned(self, plugin: OSVPlugin, spdx3_file: Path) -> None:
        seen: dict[str, Any] = {}

        def fake_scanner(scanner_path: str, scan_path: Path, timeout: int) -> tuple[str, str, int]:
            seen["path"] = Path(scan_path)
            seen["bytes"] = Path(scan_path).read_bytes()
            return CLEAN_SCAN

        with (
            patch("sbomify.apps.plugins.builtins.osv.convert_sbom", return_value=CONVERTED),
            patch.object(plugin, "_execute_scanner", side_effect=fake_scanner),
        ):
            plugin.assess("sbom-1", spdx3_file)

        assert seen["bytes"] == CONVERTED
        assert seen["path"] != spdx3_file, "the scanner must not be handed the stored document"

    def test_the_stored_document_is_left_alone(self, plugin: OSVPlugin, spdx3_file: Path) -> None:
        with (
            patch("sbomify.apps.plugins.builtins.osv.convert_sbom", return_value=CONVERTED),
            patch.object(plugin, "_execute_scanner", return_value=CLEAN_SCAN),
        ):
            plugin.assess("sbom-1", spdx3_file)

        assert spdx3_file.read_text() == SPDX3

    def test_the_result_says_it_scanned_a_conversion(self, plugin: OSVPlugin, spdx3_file: Path) -> None:
        """A surprising finding has to be traceable to the derivation."""
        with (
            patch("sbomify.apps.plugins.builtins.osv.convert_sbom", return_value=CONVERTED),
            patch.object(plugin, "_execute_scanner", return_value=CLEAN_SCAN),
        ):
            result = _as_dict(plugin.assess("sbom-1", spdx3_file))

        metadata = result["metadata"]
        assert metadata["converted_from"] == "SPDX-3.0"
        assert metadata["converted_to"] == "SPDX-2.3"
        assert metadata["sbom_format"] == "spdx3", "the format reported is the one the user uploaded"

    def test_the_derived_copy_does_not_outlive_the_scan(self, plugin: OSVPlugin, spdx3_file: Path) -> None:
        with (
            patch("sbomify.apps.plugins.builtins.osv.convert_sbom", return_value=CONVERTED),
            patch.object(plugin, "_execute_scanner", return_value=CLEAN_SCAN),
        ):
            plugin.assess("sbom-1", spdx3_file)

        assert list(spdx3_file.parent.iterdir()) == [spdx3_file]


class TestTheYoctoOutcomeIsTraceable:
    def test_a_converted_scan_that_recognises_nothing_still_says_it_converted(
        self, plugin: OSVPlugin, spdx3_file: Path
    ) -> None:
        """The path a Yocto document takes, and the one most needing an explanation."""
        with (
            patch("sbomify.apps.plugins.builtins.osv.convert_sbom", return_value=CONVERTED),
            patch.object(
                plugin,
                "_execute_scanner",
                return_value=('{"results": []}', "Scanned /tmp/x.spdx.json file and found 0 packages", 0),
            ),
        ):
            result = _as_dict(plugin.assess("sbom-1", spdx3_file))

        assert result["findings"][0]["id"] == "osv:no-packages"
        assert result["metadata"]["converted_from"] == "SPDX-3.0"
        assert result["metadata"]["converted_to"] == "SPDX-2.3"


class TestWhatStillSkips:
    def test_no_converter_installed_keeps_the_old_skip(self, plugin: OSVPlugin, spdx3_file: Path) -> None:
        """A deployment without the binary behaves exactly as it did before."""
        with (
            patch("sbomify.apps.plugins.builtins.osv.convert_sbom", side_effect=ConversionUnavailable("none")),
            patch.object(plugin, "_execute_scanner") as scanner,
        ):
            result = _as_dict(plugin.assess("sbom-1", spdx3_file))

        scanner.assert_not_called()
        assert result["findings"][0]["id"] == "osv:unsupported-format"
        assert result["metadata"]["skipped"] is True

    def test_a_converter_that_will_not_run_says_which_problem_it_is(self, plugin: OSVPlugin, spdx3_file: Path) -> None:
        """Installed but unrunnable is not the same as absent.

        An operator told "no converter installed" would go looking for a
        missing binary rather than a wrong architecture.
        """
        with (
            patch(
                "sbomify.apps.plugins.builtins.osv.convert_sbom",
                side_effect=ConversionUnavailable("converter could not be run: [Errno 8] Exec format error"),
            ),
            patch.object(plugin, "_execute_scanner") as scanner,
        ):
            result = _as_dict(plugin.assess("sbom-1", spdx3_file))

        scanner.assert_not_called()
        assert result["findings"][0]["id"] == "osv:unsupported-format"
        assert "Exec format error" in result["metadata"]["conversion_error"]

    def test_a_document_the_converter_refuses_is_its_own_skip(self, plugin: OSVPlugin, spdx3_file: Path) -> None:
        with (
            patch(
                "sbomify.apps.plugins.builtins.osv.convert_sbom",
                side_effect=ConversionFailed("no SPDX document found"),
            ),
            patch.object(plugin, "_execute_scanner") as scanner,
        ):
            result = _as_dict(plugin.assess("sbom-1", spdx3_file))

        scanner.assert_not_called()
        assert result["findings"][0]["id"] == "osv:conversion-failed"
        assert result["metadata"]["skipped"] is True
        assert "no SPDX document found" in result["metadata"]["conversion_error"]


class TestFormatsTheScannerAlreadyReads:
    def test_cyclonedx_is_not_converted(self, plugin: OSVPlugin, tmp_path: Path) -> None:
        path = tmp_path / "scan.cdx.json"
        path.write_text('{"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []}')

        with (
            patch("sbomify.apps.plugins.builtins.osv.convert_sbom") as convert,
            patch.object(plugin, "_execute_scanner", return_value=CLEAN_SCAN),
        ):
            plugin.assess("sbom-1", path)

        convert.assert_not_called()

    def test_spdx_2_is_not_converted(self, plugin: OSVPlugin, tmp_path: Path) -> None:
        path = tmp_path / "scan.spdx.json"
        path.write_text('{"spdxVersion": "SPDX-2.3", "packages": []}')

        with (
            patch("sbomify.apps.plugins.builtins.osv.convert_sbom") as convert,
            patch.object(plugin, "_execute_scanner", return_value=CLEAN_SCAN),
        ):
            plugin.assess("sbom-1", path)

        convert.assert_not_called()
