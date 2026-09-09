"""SPDX 3 reaches the scanner through a derived copy rather than a shrug.

osv-scanner has no SPDX 3 reader, so these documents used to come back as a
skip telling the uploader to convert the file themselves. The scan path now
does that conversion, scans the copy, and reports the findings against the
stored artifact, which is never touched (ADR-004).

The one skip that remains is the honest one: a document that names no package
to scan, which no conversion can rescue.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sbomify.apps.plugins.builtins.osv import OSVPlugin
from sbomify.apps.sboms.conversion import CYCLONEDX_1_6, ConversionFailed

SPDX3 = json.dumps({"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": []})
CONVERTED = b'{"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []}'
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
            patch("sbomify.apps.plugins.builtins.osv.to_cyclonedx", return_value=CONVERTED),
            patch.object(plugin, "_execute_scanner", side_effect=fake_scanner),
        ):
            plugin.assess("sbom-1", spdx3_file)

        assert seen["bytes"] == CONVERTED
        assert seen["path"] != spdx3_file, "the scanner must not be handed the stored document"

    def test_the_stored_document_is_left_alone(self, plugin: OSVPlugin, spdx3_file: Path) -> None:
        with (
            patch("sbomify.apps.plugins.builtins.osv.to_cyclonedx", return_value=CONVERTED),
            patch.object(plugin, "_execute_scanner", return_value=CLEAN_SCAN),
        ):
            plugin.assess("sbom-1", spdx3_file)

        assert spdx3_file.read_text() == SPDX3

    def test_the_result_says_it_scanned_a_conversion(self, plugin: OSVPlugin, spdx3_file: Path) -> None:
        """A surprising finding has to be traceable to the derivation."""
        with (
            patch("sbomify.apps.plugins.builtins.osv.to_cyclonedx", return_value=CONVERTED),
            patch.object(plugin, "_execute_scanner", return_value=CLEAN_SCAN),
        ):
            result = _as_dict(plugin.assess("sbom-1", spdx3_file))

        metadata = result["metadata"]
        assert metadata["converted_from"] == "SPDX-3.0"
        assert metadata["converted_to"] == CYCLONEDX_1_6
        assert metadata["sbom_format"] == "spdx3", "the format reported is the one the user uploaded"

    def test_the_derived_name_carries_no_trace_of_the_original_suffix(self, plugin: OSVPlugin, tmp_path: Path) -> None:
        """osv-scanner picks its extractor by suffix, and matches more than one.

        A name built from the original's stem keeps ``.spdx`` in the middle of
        ``x.spdx.converted.cdx.json``. The SPDX extractor then runs against
        CycloneDX content, fails, and takes the whole run down with exit 127.
        """
        source = tmp_path / "core-image-minimal.spdx.json"
        source.write_text(SPDX3)
        scanned: list[Path] = []

        def fake_scanner(scanner_path: str, scan_path: Path, timeout: int) -> tuple[str, str, int]:
            scanned.append(scan_path)
            return CLEAN_SCAN

        with (
            patch("sbomify.apps.plugins.builtins.osv.to_cyclonedx", return_value=CONVERTED),
            patch.object(plugin, "_execute_scanner", side_effect=fake_scanner),
        ):
            plugin.assess("sbom-1", source)

        assert scanned, "the scanner was never called"
        assert ".spdx" not in scanned[0].name
        assert scanned[0].name.endswith(".cdx.json")

    def test_the_derived_copy_does_not_outlive_the_scan(self, plugin: OSVPlugin, spdx3_file: Path) -> None:
        with (
            patch("sbomify.apps.plugins.builtins.osv.to_cyclonedx", return_value=CONVERTED),
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
            patch("sbomify.apps.plugins.builtins.osv.to_cyclonedx", return_value=CONVERTED),
            patch.object(
                plugin,
                "_execute_scanner",
                return_value=('{"results": []}', "Scanned /tmp/x.spdx.json file and found 0 packages", 0),
            ),
        ):
            result = _as_dict(plugin.assess("sbom-1", spdx3_file))

        assert result["findings"][0]["id"] == "osv:no-packages"
        assert result["metadata"]["converted_from"] == "SPDX-3.0"
        assert result["metadata"]["converted_to"] == CYCLONEDX_1_6


class TestWhatStillSkips:
    def test_a_document_naming_no_package_is_its_own_skip(self, plugin: OSVPlugin, tmp_path: Path) -> None:
        """No binary to be missing any more, so this is the only skip left.

        It runs through the real emitter rather than a patched one: an SPDX 3
        document with an empty graph is exactly the case that used to reach the
        scanner as an empty bill and report back as a clean scan.
        """
        path = tmp_path / "empty.json"
        path.write_text(SPDX3)

        with patch.object(plugin, "_execute_scanner") as scanner:
            result = _as_dict(plugin.assess("sbom-1", path))

        scanner.assert_not_called()
        assert result["findings"][0]["id"] == "osv:conversion-failed"
        assert result["metadata"]["skipped"] is True
        assert "names no package" in result["metadata"]["conversion_error"]

    def test_a_document_the_converter_refuses_is_its_own_skip(self, plugin: OSVPlugin, spdx3_file: Path) -> None:
        with (
            patch(
                "sbomify.apps.plugins.builtins.osv.to_cyclonedx",
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
            patch("sbomify.apps.plugins.builtins.osv.to_cyclonedx") as convert,
            patch.object(plugin, "_execute_scanner", return_value=CLEAN_SCAN),
        ):
            plugin.assess("sbom-1", path)

        convert.assert_not_called()

    def test_spdx_2_is_not_converted(self, plugin: OSVPlugin, tmp_path: Path) -> None:
        path = tmp_path / "scan.spdx.json"
        path.write_text('{"spdxVersion": "SPDX-2.3", "packages": []}')

        with (
            patch("sbomify.apps.plugins.builtins.osv.to_cyclonedx") as convert,
            patch.object(plugin, "_execute_scanner", return_value=CLEAN_SCAN),
        ):
            plugin.assess("sbom-1", path)

        convert.assert_not_called()


class TestCarryingTheCpeMustNotReadAsACleanScan:
    """Preserving CPEs changed what osv-scanner counts, and nearly cost the guard.

    A Yocto document's purls are a type osv-scanner rejects. With nothing else
    on the component it counts zero packages and the "recognised nothing" skip
    fires. Carry the CPE, which Dependency Track needs to match at all, and the
    same component is counted and then filtered as unscannable, so a count of
    what was parsed says one package and the run reads as a clean scan over a
    build nothing was matched against.
    """

    SCANNED_THEN_FILTERED = (
        "Scanned /tmp/x.cdx.json file and found 1 package\nFiltered 1 local/unscannable package/s from the scan.\n"
    )

    def test_a_package_that_was_filtered_did_not_get_matched(self, plugin: OSVPlugin) -> None:
        assert plugin._matchable_package_count(self.SCANNED_THEN_FILTERED) == 0

    def test_a_real_scan_is_not_turned_into_a_skip(self, plugin: OSVPlugin) -> None:
        assert plugin._matchable_package_count("found 500 packages") == 500
        assert plugin._matchable_package_count("found 10 packages\nFiltered 3 local package/s") == 7

    def test_a_scanner_that_says_nothing_is_not_guessed_at(self, plugin: OSVPlugin) -> None:
        """None rather than 0, so a differently phrased scanner does not turn
        every clean scan into a skip."""
        assert plugin._matchable_package_count("some other output") is None

    def test_the_whole_path_reports_a_yocto_document_as_skipped(self, plugin: OSVPlugin, tmp_path: Path) -> None:
        """The outcome that matters: no green badge over an unmatched build."""
        path = tmp_path / "yocto.json"
        path.write_text(
            json.dumps(
                {
                    "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
                    "@graph": [
                        {
                            "type": "software_Package",
                            "spdxId": "urn:p",
                            "name": "openssl",
                            "software_packageVersion": "3.0.11",
                            "software_packageUrl": "pkg:yocto/meta/openssl@3.0.11",
                            "externalIdentifier": [
                                {
                                    "externalIdentifierType": "cpe23",
                                    "identifier": "cpe:2.3:a:openssl:openssl:3.0.11:*:*:*:*:*:*:*",
                                }
                            ],
                        }
                    ],
                }
            )
        )

        with patch.object(plugin, "_execute_scanner", return_value=("{}", self.SCANNED_THEN_FILTERED, 0)):
            result = _as_dict(plugin.assess("sbom-1", path))

        assert result["findings"][0]["id"] == "osv:no-packages"
        assert result["metadata"]["skipped"] is True
        assert result["metadata"]["converted_from"] == "SPDX-3.0"
