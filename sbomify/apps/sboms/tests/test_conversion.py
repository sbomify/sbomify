"""The derived-copy path, exercised against a real subprocess.

The converter is an external binary, so these run one rather than mocking the
call: the failure this module has to get right is a converter that refuses a
document while still exiting 0, and only a real process reproduces that.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from django.test import override_settings

from sbomify.apps.sboms.conversion import (
    CYCLONEDX_1_6_JSON,
    SPDX_2_3_JSON,
    ConversionFailed,
    ConversionUnavailable,
    _package_key,
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

    def test_a_file_that_is_not_executable_is_not_the_converter(self, tmp_path: Path) -> None:
        not_a_binary = tmp_path / "syft"
        not_a_binary.write_text("this is not a program")
        with override_settings(SBOM_CONVERTER_PATH=str(not_a_binary)):
            assert converter_path() is None

    def test_the_bare_default_does_not_pick_up_a_local_file(self, tmp_path: Path, monkeypatch) -> None:
        """A syft in the working directory must not answer for a name on PATH."""
        _stub_converter(tmp_path, 'echo "{}"\n')  # tmp_path/stub-converter
        (tmp_path / "syft").write_text("#!/bin/sh\necho '{}'\n")
        (tmp_path / "syft").chmod(0o755)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PATH", "/nonexistent-for-this-test")
        with override_settings(SBOM_CONVERTER_PATH="syft"):
            assert converter_path() is None


class TestConversion:
    def test_the_converted_document_comes_back(self, tmp_path: Path) -> None:
        binary = _stub_converter(tmp_path, 'echo \'{"bomFormat":"CycloneDX"}\'\n')
        with override_settings(SBOM_CONVERTER_PATH=binary):
            assert b"CycloneDX" in convert_sbom(DOCUMENT, "cyclonedx-json@1.6")

    def test_the_source_document_reaches_the_converter(self, tmp_path: Path) -> None:
        """It is passed as a file, so the stub proves the file holds our bytes.

        The source here is already SPDX 2.3, because the stub echoes it back
        as the conversion's output and the output has to be the format the
        caller asked for.
        """
        source = b'{"spdxVersion": "SPDX-2.3", "name": "echoed"}'
        binary = _stub_converter(tmp_path, 'cat "$2"\n')  # argv: convert <source> -o <format>
        with override_settings(SBOM_CONVERTER_PATH=binary):
            assert convert_sbom(source, SPDX_2_3_JSON) == source

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

    def test_output_that_only_starts_like_a_document_is_a_failure(self, tmp_path: Path) -> None:
        """Truncated output would otherwise reach a scanner and read as its fault."""
        binary = _stub_converter(tmp_path, 'printf \'{"bomFormat": "Cyclone\'\n')
        with override_settings(SBOM_CONVERTER_PATH=binary):
            with pytest.raises(ConversionFailed, match="no usable document"):
                convert_sbom(DOCUMENT, "spdx-json")

    @pytest.mark.parametrize("output", ["{}", "[]", '{"error": "cannot read this"}', '"a string"', "null"])
    def test_valid_json_that_is_not_an_sbom_is_a_failure(self, tmp_path: Path, output: str) -> None:
        """A scanner handed an error object would report our failure as its own."""
        binary = _stub_converter(tmp_path, f"cat <<'JSON'\n{output}\nJSON\n")
        with override_settings(SBOM_CONVERTER_PATH=binary):
            with pytest.raises(ConversionFailed, match="no usable document"):
                convert_sbom(b"{}", SPDX_2_3_JSON)

    def test_the_output_must_be_the_format_that_was_asked_for(self, tmp_path: Path) -> None:
        """SPDX output where CycloneDX was requested is a conversion failure, not a scan."""
        binary = _stub_converter(tmp_path, 'cat <<\'JSON\'\n{"spdxVersion": "SPDX-2.3"}\nJSON\n')
        with override_settings(SBOM_CONVERTER_PATH=binary):
            with pytest.raises(ConversionFailed, match="no bomFormat"):
                convert_sbom(b"{}", CYCLONEDX_1_6_JSON)

            assert json.loads(convert_sbom(b"{}", SPDX_2_3_JSON))["spdxVersion"] == "SPDX-2.3"

    def test_a_hanging_converter_is_killed(self, tmp_path: Path) -> None:
        binary = _stub_converter(tmp_path, "sleep 30\n")
        with override_settings(SBOM_CONVERTER_PATH=binary):
            with pytest.raises(ConversionFailed, match="timed out"):
                convert_sbom(DOCUMENT, "spdx-json", timeout=1)

    def test_the_temporary_source_file_does_not_survive(self, tmp_path: Path) -> None:
        """The derived copy is for one scan; nothing it touches should linger."""
        leaked = tmp_path / "leaked-path"
        binary = _stub_converter(tmp_path, f'printf "%s" "$2" > {leaked}\necho \'{{"spdxVersion": "SPDX-2.3"}}\'\n')
        with override_settings(SBOM_CONVERTER_PATH=binary):
            convert_sbom(DOCUMENT, "spdx-json")
        assert not Path(leaked.read_text()).exists()


CPE = "cpe:2.3:a:openssl:openssl:3.0.11:*:*:*:*:*:*:*"


class TestTheCpeSurvives:
    """A converter carries purls across and drops the CPE.

    For a build system whose purl type no scanner maps, Yocto's ``pkg:yocto``
    being the case in hand, the CPE is the only identifier left that a scanner
    can match on, so losing it in a copy made for scanning loses the scan.
    """

    SPDX3_WITH_CPE = json.dumps(
        {
            "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
            "@graph": [
                {
                    "type": "software_Package",
                    "spdxId": "urn:pkg",
                    "name": "openssl",
                    "software_packageVersion": "3.0.11",
                    "software_packageUrl": "pkg:yocto/meta/openssl@3.0.11",
                    "externalIdentifier": [{"externalIdentifierType": "cpe23", "identifier": CPE}],
                }
            ],
        }
    ).encode()

    def _converter_emitting(self, tmp_path: Path, document: dict[str, Any]) -> str:
        return _stub_converter(tmp_path, f"cat <<'JSON'\n{json.dumps(document)}\nJSON\n")

    def test_it_is_put_back_on_the_spdx_copy(self, tmp_path: Path) -> None:
        binary = self._converter_emitting(
            tmp_path,
            {"spdxVersion": "SPDX-2.3", "packages": [{"name": "openssl", "versionInfo": "3.0.11"}]},
        )
        with override_settings(SBOM_CONVERTER_PATH=binary):
            converted = json.loads(convert_sbom(self.SPDX3_WITH_CPE, "spdx-json"))

        refs = converted["packages"][0]["externalRefs"]
        assert refs == [
            {
                "referenceCategory": "SECURITY",
                "referenceType": "cpe23Type",
                "referenceLocator": CPE,
            }
        ]

    def test_it_is_put_back_on_the_cyclonedx_copy(self, tmp_path: Path) -> None:
        binary = self._converter_emitting(
            tmp_path,
            {"bomFormat": "CycloneDX", "components": [{"name": "openssl", "version": "3.0.11"}]},
        )
        with override_settings(SBOM_CONVERTER_PATH=binary):
            converted = json.loads(convert_sbom(self.SPDX3_WITH_CPE, "cyclonedx-json@1.6"))

        assert converted["components"][0]["cpe"] == CPE

    def test_a_package_the_source_says_nothing_about_is_left_alone(self, tmp_path: Path) -> None:
        binary = self._converter_emitting(
            tmp_path,
            {"spdxVersion": "SPDX-2.3", "packages": [{"name": "zlib", "versionInfo": "1.3"}]},
        )
        with override_settings(SBOM_CONVERTER_PATH=binary):
            converted = json.loads(convert_sbom(self.SPDX3_WITH_CPE, "spdx-json"))

        assert "externalRefs" not in converted["packages"][0]

    def test_a_cpe_the_converter_kept_is_not_repeated(self, tmp_path: Path) -> None:
        binary = self._converter_emitting(
            tmp_path,
            {
                "spdxVersion": "SPDX-2.3",
                "packages": [
                    {
                        "name": "openssl",
                        "versionInfo": "3.0.11",
                        "externalRefs": [
                            {
                                "referenceCategory": "SECURITY",
                                "referenceType": "cpe23Type",
                                "referenceLocator": CPE,
                            }
                        ],
                    }
                ],
            },
        )
        with override_settings(SBOM_CONVERTER_PATH=binary):
            converted = json.loads(convert_sbom(self.SPDX3_WITH_CPE, "spdx-json"))

        assert len(converted["packages"][0]["externalRefs"]) == 1

    def test_a_cpe_in_the_2_2_form_is_filed_under_its_own_type(self, tmp_path: Path) -> None:
        """The value decides the reference type, not the label the source gave it."""
        source = json.dumps(
            {
                "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
                "@graph": [
                    {
                        "type": "software_Package",
                        "spdxId": "urn:pkg",
                        "name": "openssl",
                        "software_packageVersion": "3.0.11",
                        "externalIdentifier": [
                            {"externalIdentifierType": "cpe22", "identifier": "cpe:/a:openssl:openssl:3.0.11"},
                            {"externalIdentifierType": "cpe23", "identifier": "cpe:not-a-cpe"},
                        ],
                    }
                ],
            }
        ).encode()
        binary = self._converter_emitting(
            tmp_path,
            {"spdxVersion": "SPDX-2.3", "packages": [{"name": "openssl", "versionInfo": "3.0.11"}]},
        )
        with override_settings(SBOM_CONVERTER_PATH=binary):
            converted = json.loads(convert_sbom(source, "spdx-json"))

        assert converted["packages"][0]["externalRefs"] == [
            {
                "referenceCategory": "SECURITY",
                "referenceType": "cpe22Type",
                "referenceLocator": "cpe:/a:openssl:openssl:3.0.11",
            }
        ]

    def test_a_malformed_external_refs_field_is_replaced_not_iterated(self, tmp_path: Path) -> None:
        """A converter is a third party; what it wrote where a list belongs is not ours to trust."""
        binary = self._converter_emitting(
            tmp_path,
            {
                "spdxVersion": "SPDX-2.3",
                "packages": [{"name": "openssl", "versionInfo": "3.0.11", "externalRefs": None}],
            },
        )
        with override_settings(SBOM_CONVERTER_PATH=binary):
            converted = json.loads(convert_sbom(self.SPDX3_WITH_CPE, "spdx-json"))

        assert converted["packages"][0]["externalRefs"] == [
            {"referenceCategory": "SECURITY", "referenceType": "cpe23Type", "referenceLocator": CPE}
        ]

    @pytest.mark.parametrize("junk", [5, "packages", {"a": 1}, None])
    def test_a_non_list_where_a_list_belongs_does_not_crash(self, tmp_path: Path, junk: Any) -> None:
        """Both documents are third-party, so neither is trusted to hold a list."""
        source = json.dumps({"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": junk}).encode()
        binary = self._converter_emitting(tmp_path, {"spdxVersion": "SPDX-2.3", "packages": junk, "components": junk})
        with override_settings(SBOM_CONVERTER_PATH=binary):
            converted = json.loads(convert_sbom(source, "spdx-json"))

        assert converted["packages"] == junk

    def test_a_cpe_the_source_states_twice_is_written_once(self, tmp_path: Path) -> None:
        """A package is no more identified for having said the same thing twice."""
        source = json.dumps(
            {
                "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
                "@graph": [
                    {
                        "type": "software_Package",
                        "spdxId": "urn:pkg",
                        "name": "openssl",
                        "software_packageVersion": "3.0.11",
                        "externalIdentifier": [
                            {"externalIdentifierType": "cpe23", "identifier": CPE},
                            {"externalIdentifierType": "cpe23", "identifier": CPE},
                        ],
                    }
                ],
            }
        ).encode()
        binary = self._converter_emitting(
            tmp_path,
            {"spdxVersion": "SPDX-2.3", "packages": [{"name": "openssl", "versionInfo": "3.0.11"}]},
        )
        with override_settings(SBOM_CONVERTER_PATH=binary):
            converted = json.loads(convert_sbom(source, SPDX_2_3_JSON))

        assert [r["referenceLocator"] for r in converted["packages"][0]["externalRefs"]] == [CPE]

    def test_a_numeric_zero_version_still_matches_its_string(self, tmp_path: Path) -> None:
        """Only None is a missing version, so 0 is not folded onto the empty string."""
        source = json.dumps(
            {
                "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
                "@graph": [
                    {
                        "type": "software_Package",
                        "spdxId": "urn:pkg",
                        "name": "widget",
                        "software_packageVersion": 0,
                        "externalIdentifier": [{"externalIdentifierType": "cpe23", "identifier": CPE}],
                    }
                ],
            }
        ).encode()
        binary = self._converter_emitting(
            tmp_path,
            {"spdxVersion": "SPDX-2.3", "packages": [{"name": "widget", "versionInfo": "0"}]},
        )
        with override_settings(SBOM_CONVERTER_PATH=binary):
            converted = json.loads(convert_sbom(source, SPDX_2_3_JSON))

        assert converted["packages"][0]["externalRefs"][0]["referenceLocator"] == CPE

    def test_a_whitespace_name_is_no_name(self) -> None:
        """Otherwise every such package shares one key and they collide."""
        assert _package_key("   ", "1.0") is None
        assert _package_key("openssl", None) == ("openssl", "")
        assert _package_key(" OpenSSL ", " 3.0.11 ") == ("openssl", "3.0.11")

    def test_a_source_with_no_cpe_changes_nothing(self, tmp_path: Path) -> None:
        emitted = {"spdxVersion": "SPDX-2.3", "packages": [{"name": "openssl", "versionInfo": "3.0.11"}]}
        binary = self._converter_emitting(tmp_path, emitted)
        with override_settings(SBOM_CONVERTER_PATH=binary):
            converted = json.loads(convert_sbom(b'{"@graph": []}', "spdx-json"))

        assert converted == emitted


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
            ref["referenceLocator"] for package in converted["packages"] for ref in package.get("externalRefs") or []
        ]
        assert "pkg:generic/openssl@3.0.11" in locators
