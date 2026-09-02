"""The derived-copy path, exercised against a real subprocess.

The converter is an external binary, so these run one rather than mocking the
call: the failure this module has to get right is a converter that refuses a
document while still exiting 0, and only a real process reproduces that.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from django.test import override_settings

from sbomify.apps.sboms.conversion import (
    ConversionFailed,
    ConversionUnavailable,
    convert_sbom,
    converter_path,
)

DOCUMENT = b'{"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": []}'


def _stub_converter(tmp_path: Path, body: str) -> str:
    script = tmp_path / "stub-converter"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(script)


class TestConverterAvailability:
    def test_a_missing_converter_is_not_a_failed_conversion(self, tmp_path: Path) -> None:
        """The caller degrades to its old behaviour, so the two must not merge."""
        with override_settings(SBOM_CONVERTER_PATH=str(tmp_path / "nothing-here")):
            assert converter_path() is None
            with pytest.raises(ConversionUnavailable):
                convert_sbom(DOCUMENT, "spdx-json")

    def test_an_absolute_path_to_a_real_file_is_used(self, tmp_path: Path) -> None:
        binary = _stub_converter(tmp_path, 'echo "{}"\n')
        with override_settings(SBOM_CONVERTER_PATH=binary):
            assert converter_path() == binary


class TestConversion:
    def test_the_converted_document_comes_back(self, tmp_path: Path) -> None:
        binary = _stub_converter(tmp_path, 'echo \'{"bomFormat":"CycloneDX"}\'\n')
        with override_settings(SBOM_CONVERTER_PATH=binary):
            assert b"CycloneDX" in convert_sbom(DOCUMENT, "cyclonedx-json@1.6")

    def test_the_source_document_reaches_the_converter(self, tmp_path: Path) -> None:
        """It is passed as a file, so the stub proves the file holds our bytes."""
        binary = _stub_converter(tmp_path, 'cat "$2"\n')  # argv: convert <source> -o <format>
        with override_settings(SBOM_CONVERTER_PATH=binary):
            assert convert_sbom(DOCUMENT, "spdx-json") == DOCUMENT

    def test_a_refusal_that_still_exits_zero_is_a_failure(self, tmp_path: Path) -> None:
        """How the real converter reports a document it cannot read."""
        binary = _stub_converter(tmp_path, 'echo "failed to decode SBOM: not recognized" >&2\nexit 0\n')
        with override_settings(SBOM_CONVERTER_PATH=binary):
            with pytest.raises(ConversionFailed, match="not recognized"):
                convert_sbom(DOCUMENT, "spdx-json")

    def test_a_non_zero_exit_is_a_failure(self, tmp_path: Path) -> None:
        binary = _stub_converter(tmp_path, 'echo "boom" >&2\nexit 3\n')
        with override_settings(SBOM_CONVERTER_PATH=binary):
            with pytest.raises(ConversionFailed):
                convert_sbom(DOCUMENT, "spdx-json")

    def test_output_that_is_not_a_document_is_a_failure(self, tmp_path: Path) -> None:
        binary = _stub_converter(tmp_path, 'echo "syft-table output, not json"\n')
        with override_settings(SBOM_CONVERTER_PATH=binary):
            with pytest.raises(ConversionFailed):
                convert_sbom(DOCUMENT, "spdx-json")

    def test_a_hanging_converter_is_killed(self, tmp_path: Path) -> None:
        binary = _stub_converter(tmp_path, "sleep 30\n")
        with override_settings(SBOM_CONVERTER_PATH=binary):
            with pytest.raises(ConversionFailed, match="timed out"):
                convert_sbom(DOCUMENT, "spdx-json", timeout=1)

    def test_the_temporary_source_file_does_not_survive(self, tmp_path: Path) -> None:
        """The derived copy is for one scan; nothing it touches should linger."""
        leaked = tmp_path / "leaked-path"
        binary = _stub_converter(tmp_path, f'printf "%s" "$2" > {leaked}\necho "{{}}"\n')
        with override_settings(SBOM_CONVERTER_PATH=binary):
            convert_sbom(DOCUMENT, "spdx-json")
        assert not Path(leaked.read_text()).exists()


@pytest.mark.skipif(not os.environ.get("SBOM_CONVERTER_E2E"), reason="needs a real converter installed")
class TestAgainstTheRealConverter:
    def test_spdx3_converts_and_keeps_its_purls(self) -> None:
        """Purl survival is what lets findings line up with the stored original."""
        import json

        document = json.dumps(
            {
                "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
                "@graph": [
                    {
                        "type": "CreationInfo",
                        "@id": "_:ci",
                        "specVersion": "3.0.1",
                        "created": "2026-01-01T00:00:00Z",
                        "createdBy": ["urn:agent"],
                    },
                    {"type": "SoftwareAgent", "spdxId": "urn:agent", "creationInfo": "_:ci", "name": "builder"},
                    {
                        # The converter needs the document element to recognise
                        # the graph as SPDX at all.
                        "type": "SpdxDocument",
                        "spdxId": "urn:doc",
                        "creationInfo": "_:ci",
                        "name": "image",
                        "rootElement": ["urn:pkg"],
                    },
                    {
                        "type": "software_Package",
                        "spdxId": "urn:pkg",
                        "creationInfo": "_:ci",
                        "name": "openssl",
                        "software_packageVersion": "3.0.11",
                        "software_packageUrl": "pkg:generic/openssl@3.0.11",
                    },
                ],
            }
        ).encode()

        converted = json.loads(convert_sbom(document, "spdx-json"))

        assert converted["spdxVersion"] == "SPDX-2.3"
        locators = [
            ref["referenceLocator"]
            for package in converted["packages"]
            for ref in package.get("externalRefs") or []
        ]
        assert "pkg:generic/openssl@3.0.11" in locators
