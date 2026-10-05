"""The scanner-readable copy, and what it is allowed to lose.

The copy exists so a scanner that cannot read the stored format still sees the
packages. What it must carry is therefore exactly what a scanner matches on:
the package, its version, its purl and its CPE. What it may drop is everything
read from the stored original instead.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sbomify.apps.sboms.conversion import (
    CYCLONEDX_1_6,
    ConversionFailed,
    _cyclonedx_validator,
    downgrade_cyclonedx,
    to_cyclonedx,
)

OSV_SCANNER = Path("/usr/local/bin/osv-scanner")


def spdx3(*packages: dict) -> bytes:
    return json.dumps(
        {
            "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
            "@graph": [
                {"type": "SpdxDocument", "spdxId": "urn:doc", "name": "doc"},
                {"type": "software_Sbom", "spdxId": "urn:sbom", "software_sbomType": "build"},
                *packages,
            ],
        }
    ).encode()


def spdx2(*packages: dict) -> bytes:
    return json.dumps(
        {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "documentNamespace": "https://acme.example/1",
            "creationInfo": {"created": "2026-09-07T00:00:00Z", "creators": ["Organization: Acme"]},
            "packages": list(packages),
        }
    ).encode()


def components(data: bytes) -> list[dict]:
    return json.loads(to_cyclonedx(data))["components"]


class TestTheCopyIsCycloneDX:
    def test_it_declares_the_version_dependency_track_reads(self) -> None:
        out = json.loads(to_cyclonedx(spdx3({"type": "software_Package", "spdxId": "urn:p", "name": "openssl"})))

        assert out["bomFormat"] == "CycloneDX"
        assert out["specVersion"] == "1.6"
        assert CYCLONEDX_1_6.endswith(out["specVersion"])

    def test_it_says_what_it_was_derived_from(self) -> None:
        """A copy that outlives its scan directory must not read as an upload."""
        out = json.loads(to_cyclonedx(spdx3({"type": "software_Package", "spdxId": "urn:p", "name": "openssl"})))

        properties = {p["name"]: p["value"] for p in out["metadata"]["properties"]}
        assert properties["sbomify:derived_from"] == "SPDX-3.0"


class TestWhatTheScannerMatchesOnSurvives:
    def test_spdx3_carries_the_purl(self) -> None:
        got = components(
            spdx3(
                {
                    "type": "software_Package",
                    "spdxId": "urn:p",
                    "name": "jinja2",
                    "software_packageVersion": "2.11.2",
                    "software_packageUrl": "pkg:pypi/jinja2@2.11.2",
                }
            )
        )

        assert got == [
            {
                "type": "library",
                "name": "jinja2",
                "bom-ref": "urn:p",
                "version": "2.11.2",
                "purl": "pkg:pypi/jinja2@2.11.2",
            }
        ]

    def test_spdx3_carries_the_cpe_a_converter_would_drop(self) -> None:
        """The whole of the CPE-preservation problem, solved by emitting it."""
        got = components(
            spdx3(
                {
                    "type": "software_Package",
                    "spdxId": "urn:p",
                    "name": "openssl",
                    "software_packageVersion": "3.0.11",
                    "externalIdentifier": [
                        {
                            "externalIdentifierType": "cpe23",
                            "identifier": "cpe:2.3:a:openssl:openssl:3.0.11:*:*:*:*:*:*:*",
                        }
                    ],
                }
            )
        )

        assert got[0]["cpe"] == "cpe:2.3:a:openssl:openssl:3.0.11:*:*:*:*:*:*:*"

    def test_spdx2_carries_both_from_external_refs(self) -> None:
        got = components(
            spdx2(
                {
                    "name": "openssl",
                    "SPDXID": "SPDXRef-a",
                    "versionInfo": "3.0.11",
                    "externalRefs": [
                        {"referenceType": "purl", "referenceLocator": "pkg:generic/openssl@3.0.11"},
                        {
                            "referenceType": "cpe23Type",
                            "referenceLocator": "cpe:2.3:a:openssl:openssl:3.0.11:*:*:*:*:*:*:*",
                        },
                    ],
                }
            )
        )

        assert got[0]["purl"] == "pkg:generic/openssl@3.0.11"
        assert got[0]["cpe"].startswith("cpe:2.3:a:openssl")

    @pytest.mark.parametrize(
        "reference_type",
        ["cpe23Type", "http://spdx.org/rdf/references/cpe23Type"],
    )
    def test_the_type_is_read_whether_or_not_it_is_written_as_an_iri(self, reference_type: str) -> None:
        """Yocto writes the IRI form for every reference in every document it emits."""
        got = components(
            spdx2(
                {
                    "name": "openssl",
                    "SPDXID": "SPDXRef-Recipe-openssl",
                    "versionInfo": "3.2.3",
                    "externalRefs": [
                        {
                            "referenceCategory": "SECURITY",
                            "referenceType": reference_type,
                            "referenceLocator": "cpe:2.3:*:openssl:openssl:3.2.3:*:*:*:*:*:*:*",
                        }
                    ],
                }
            )
        )

        assert got[0]["cpe"] == "cpe:2.3:*:openssl:openssl:3.2.3:*:*:*:*:*:*:*"

    def test_a_bare_purl_on_an_spdx2_package_counts(self) -> None:
        """Not in the spec, but producers write it and the plugins read it."""
        got = components(spdx2({"name": "jinja2", "SPDXID": "SPDXRef-a", "purl": "pkg:pypi/jinja2@2.11.2"}))

        assert got[0]["purl"] == "pkg:pypi/jinja2@2.11.2"

    @pytest.mark.parametrize("spelling", ["software_Package", "Package", "software:Package"])
    def test_every_spelling_of_the_type_is_read(self, spelling: str) -> None:
        got = components(spdx3({"type": spelling, "spdxId": "urn:p", "name": "openssl"}))

        assert len(got) == 1


class TestWhatIsRefused:
    @pytest.mark.parametrize("junk", [b"", b"not json", b"[]", b'"text"', b"\xff\xfe"])
    def test_a_document_that_is_not_an_object_is_refused(self, junk: bytes) -> None:
        with pytest.raises(ConversionFailed):
            to_cyclonedx(junk)

    def test_a_format_that_is_not_spdx_is_refused(self) -> None:
        with pytest.raises(ConversionFailed, match="not an SPDX document"):
            to_cyclonedx(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6"}).encode())

    def test_a_document_naming_no_package_is_refused(self) -> None:
        """An empty bill would report as a clean scan."""
        with pytest.raises(ConversionFailed, match="names no package"):
            to_cyclonedx(spdx3())

    def test_a_package_without_a_name_is_not_a_component(self) -> None:
        got = components(
            spdx3(
                {"type": "software_Package", "spdxId": "urn:a", "name": "  "},
                {"type": "software_Package", "spdxId": "urn:b", "name": "real"},
            )
        )

        assert [c["name"] for c in got] == ["real"]

    @pytest.mark.parametrize("junk", [None, 5, "text", {"a": 1}])
    def test_a_malformed_package_list_does_not_raise_out(self, junk) -> None:
        """Uploads are untrusted, so a wrong type is a refusal, not a traceback."""
        document = json.loads(spdx2())
        document["packages"] = junk

        with pytest.raises(ConversionFailed):
            to_cyclonedx(json.dumps(document).encode())


@pytest.mark.skipif(not OSV_SCANNER.exists(), reason="osv-scanner is not installed here")
class TestTheRealScannerReadsIt:
    """The claim this whole approach rests on, checked against the binary."""

    def _scan(self, data: bytes, tmp_path: Path) -> dict:
        path = tmp_path / "derived.cdx.json"
        path.write_bytes(data)
        proc = subprocess.run(
            # The plugin's own invocation, so a flag the scanner stops
            # accepting fails here rather than passing under a form the
            # plugin does not use.
            [str(OSV_SCANNER), "scan", "source", "--lockfile", str(path), "--format", "json"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        return json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {}

    def test_osv_scanner_finds_vulnerabilities_in_a_derived_copy(self, tmp_path: Path) -> None:
        derived = to_cyclonedx(
            spdx3(
                {
                    "type": "software_Package",
                    "spdxId": "urn:p",
                    "name": "jinja2",
                    "software_packageVersion": "2.11.2",
                    "software_packageUrl": "pkg:pypi/jinja2@2.11.2",
                }
            )
        )

        found = self._scan(derived, tmp_path)

        matched = [pkg for res in found.get("results", []) for pkg in res.get("packages", [])]
        assert matched, "osv-scanner matched nothing in the derived copy"
        assert matched[0]["package"]["name"] == "jinja2"
        assert len(matched[0].get("vulnerabilities", [])) > 0


TEST_DATA = Path(__file__).parent / "test_data"


class TestDowngradingCycloneDX:
    """A copy at an older spec version, for a scanner that refuses the newer one."""

    @pytest.fixture
    def sbom_1_7(self) -> bytes:
        return (TEST_DATA / "sbom_sample_1.7.cdx.json").read_bytes()

    def test_the_fixture_is_valid_1_7_and_not_1_6(self, sbom_1_7: bytes) -> None:
        document = json.loads(sbom_1_7)
        assert not list(_cyclonedx_validator("1.7").iter_errors(document))
        assert list(_cyclonedx_validator("1.6").iter_errors(document))

    @pytest.mark.parametrize("version", ["1.6", "1.5"])
    def test_the_copy_validates_at_the_target_version(self, sbom_1_7: bytes, version: str) -> None:
        copy = json.loads(downgrade_cyclonedx(sbom_1_7, version))

        assert copy["specVersion"] == version
        assert copy["$schema"] == f"http://cyclonedx.org/schema/bom-{version}.schema.json"
        assert not list(_cyclonedx_validator(version).iter_errors(copy))

    def test_what_1_6_does_not_define_is_dropped(self, sbom_1_7: bytes) -> None:
        copy = json.loads(downgrade_cyclonedx(sbom_1_7, "1.6"))
        requests, lodash = copy["components"]

        assert "citations" not in copy
        assert "distributionConstraints" not in copy["metadata"]
        assert "isExternal" not in requests
        assert {"isExternal", "versionRange"}.isdisjoint(lodash)
        # A hash or reference whose enum value 1.6 does not list loses its
        # required member, so the entry goes and its siblings stay.
        assert [h["alg"] for h in requests["hashes"]] == ["SHA-256"]
        assert [r["type"] for r in requests["externalReferences"]] == ["vcs"]

    def test_what_a_scanner_matches_on_is_kept(self, sbom_1_7: bytes) -> None:
        original = json.loads(sbom_1_7)
        copy = json.loads(downgrade_cyclonedx(sbom_1_7, "1.6"))

        assert [c.get("purl") for c in copy["components"]] == [c.get("purl") for c in original["components"]]
        assert copy["dependencies"] == original["dependencies"]
        assert copy["metadata"]["component"] == original["metadata"]["component"]

    def test_a_1_7_cbom_validates_at_1_6(self) -> None:
        copy = json.loads(downgrade_cyclonedx((TEST_DATA / "cbom_sample_1.7.cdx.json").read_bytes(), "1.6"))

        assert not list(_cyclonedx_validator("1.6").iter_errors(copy))

    def test_a_copy_that_would_still_be_invalid_is_refused(self) -> None:
        broken = json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.7", "components": "not a list"})

        with pytest.raises(ConversionFailed, match="not valid CycloneDX 1.6"):
            downgrade_cyclonedx(broken.encode(), "1.6")

    def test_only_cyclonedx_json_is_accepted(self) -> None:
        with pytest.raises(ConversionFailed):
            downgrade_cyclonedx(json.dumps({"spdxVersion": "SPDX-2.3"}).encode(), "1.6")
        with pytest.raises(ConversionFailed):
            downgrade_cyclonedx(b"<bom xmlns='http://cyclonedx.org/schema/bom/1.7'/>", "1.6")
