"""OpenChain Telco SBOM Guide v1.1 conformance checks.

The clause numbers and wording come from the published Guide, not from the
issue, which describes it as "a field-presence profile over CycloneDX". §3.1
says the opposite: a conformant document SHALL be SPDX 2.2 or 2.3, and §3.3.2
explains the choice over CycloneDX. That is pinned first, since it is the
difference between assessing a document and assessing one that can never pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sbomify.apps.plugins.builtins.openchain_telco import OpenChainTelcoPlugin


@pytest.fixture
def plugin():
    return OpenChainTelcoPlugin()


def _conformant() -> dict:
    """A document that satisfies every machine-checkable clause."""
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "acme-gateway",
        "documentNamespace": "https://acme.test/spdx/acme-gateway-1.0",
        "creationInfo": {
            "created": "2026-07-29T00:00:00Z",
            "creators": ["Organization: Acme Corp", "Tool: syft-1.18.1"],
            "creatorComment": "SBOM Type: Build",
        },
        "packages": [
            {
                "name": "django",
                "SPDXID": "SPDXRef-Package-django",
                "versionInfo": "5.1.4",
                "supplier": "Organization: Django Software Foundation",
                "downloadLocation": "https://pypi.org/project/Django/",
                "licenseConcluded": "BSD-3-Clause",
                "licenseDeclared": "BSD-3-Clause",
                "copyrightText": "Copyright (c) Django Software Foundation",
                "checksums": [{"algorithm": "SHA256", "checksumValue": "abc123"}],
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": "pkg:pypi/django@5.1.4",
                    }
                ],
            }
        ],
        "relationships": [
            {"relationshipType": "DESCRIBES"},
            {"relationshipType": "CONTAINS"},
        ],
    }


def _run(plugin, document, tmp_path: Path):
    path = tmp_path / "sbom.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return plugin.assess("sbom-1", path)


def _by_slug(result) -> dict[str, str]:
    return {f.id.split(":", 1)[1]: f.status for f in result.findings}


class TestDataFormat:
    def test_a_conformant_spdx_document_passes_everything(self, plugin, tmp_path):
        result = _run(plugin, _conformant(), tmp_path)

        assert result.summary.fail_count == 0
        assert result.summary.warning_count == 0

    @pytest.mark.parametrize("version", ["SPDX-2.2", "SPDX-2.3"])
    def test_both_accepted_spdx_versions(self, plugin, tmp_path, version):
        document = _conformant() | {"spdxVersion": version}

        assert _by_slug(_run(plugin, document, tmp_path))["data-format"] == "pass"

    def test_an_older_spdx_version_fails(self, plugin, tmp_path):
        document = _conformant() | {"spdxVersion": "SPDX-2.1"}

        assert _by_slug(_run(plugin, document, tmp_path))["data-format"] == "fail"

    def test_cyclonedx_cannot_conform(self, plugin, tmp_path):
        """§3.1 mandates SPDX, so a CycloneDX document fails outright rather
        than being judged field by field against a profile it cannot satisfy."""
        result = _run(plugin, {"bomFormat": "CycloneDX", "specVersion": "1.6", "components": []}, tmp_path)

        statuses = _by_slug(result)
        assert statuses["data-format"] == "fail"
        # and nothing else is reported, so the one real reason is not buried
        assert list(statuses) == ["data-format"]


class TestDocumentElements:
    @pytest.mark.parametrize(
        ("field", "slug"),
        [
            ("dataLicense", "data-license"),
            ("SPDXID", "spdx-id"),
            ("name", "document-name"),
            ("documentNamespace", "document-namespace"),
        ],
    )
    def test_a_missing_required_document_field_fails(self, plugin, tmp_path, field, slug):
        document = _conformant()
        del document[field]

        assert _by_slug(_run(plugin, document, tmp_path))[slug] == "fail"

    def test_missing_creator_fails(self, plugin, tmp_path):
        document = _conformant()
        document["creationInfo"]["creators"] = []

        assert _by_slug(_run(plugin, document, tmp_path))["creator"] == "fail"


class TestPackageElements:
    @pytest.mark.parametrize(
        ("field", "slug"),
        [
            ("versionInfo", "package-version"),
            ("supplier", "package-supplier"),
            ("downloadLocation", "package-download-location"),
            ("licenseConcluded", "package-license-concluded"),
            ("licenseDeclared", "package-license-declared"),
            ("copyrightText", "package-copyright"),
        ],
    )
    def test_a_missing_required_package_field_fails(self, plugin, tmp_path, field, slug):
        document = _conformant()
        del document["packages"][0][field]

        assert _by_slug(_run(plugin, document, tmp_path))[slug] == "fail"

    def test_a_missing_hash_is_only_a_warning(self, plugin, tmp_path):
        """§3.2 marks checksum/verification code RECOMMENDED, not required."""
        document = _conformant()
        del document["packages"][0]["checksums"]

        assert _by_slug(_run(plugin, document, tmp_path))["package-hash"] == "warning"

    def test_a_verification_code_satisfies_the_hash_requirement(self, plugin, tmp_path):
        """The Guide accepts either, so one must not be reported as missing
        because the other is absent."""
        document = _conformant()
        del document["packages"][0]["checksums"]
        document["packages"][0]["packageVerificationCode"] = {"packageVerificationCodeValue": "d6a7"}

        assert _by_slug(_run(plugin, document, tmp_path))["package-hash"] == "pass"

    def test_a_missing_purl_is_only_a_warning(self, plugin, tmp_path):
        """§3.2 says a package SHOULD be identified by a PURL."""
        document = _conformant()
        del document["packages"][0]["externalRefs"]

        assert _by_slug(_run(plugin, document, tmp_path))["package-purl"] == "warning"

    def test_a_non_purl_external_ref_does_not_count(self, plugin, tmp_path):
        document = _conformant()
        document["packages"][0]["externalRefs"] = [{"referenceType": "cpe23Type", "referenceLocator": "cpe:2.3:a:x"}]

        assert _by_slug(_run(plugin, document, tmp_path))["package-purl"] == "warning"

    def test_a_document_with_no_packages_fails(self, plugin, tmp_path):
        document = _conformant() | {"packages": []}

        assert _by_slug(_run(plugin, document, tmp_path))["packages"] == "fail"

    def test_the_message_names_only_a_sample_of_offenders(self, plugin, tmp_path):
        """A thousand-package SBOM must not produce a wall of package names."""
        document = _conformant()
        document["packages"] = [{"name": f"pkg-{i}", "SPDXID": f"SPDXRef-{i}"} for i in range(20)]

        result = _run(plugin, document, tmp_path)
        finding = next(f for f in result.findings if f.id.endswith("package-version"))

        assert "and 15 more" in finding.description


class TestRelationships:
    def test_both_required_relationships_present_passes(self, plugin, tmp_path):
        assert _by_slug(_run(plugin, _conformant(), tmp_path))["relationships"] == "pass"

    def test_a_missing_contains_fails(self, plugin, tmp_path):
        document = _conformant()
        document["relationships"] = [{"relationshipType": "DESCRIBES"}]

        result = _run(plugin, document, tmp_path)
        finding = next(f for f in result.findings if f.id.endswith("relationships"))

        assert finding.status == "fail"
        assert "CONTAINS" in finding.description


class TestBuildInformation:
    def test_a_creator_without_an_organization_fails(self, plugin, tmp_path):
        document = _conformant()
        document["creationInfo"]["creators"] = ["Tool: syft-1.18.1"]

        assert _by_slug(_run(plugin, document, tmp_path))["creator-organization"] == "fail"

    def test_a_tool_without_a_version_fails(self, plugin, tmp_path):
        """§3.5 requires the Tool line to carry name and version."""
        document = _conformant()
        document["creationInfo"]["creators"] = ["Organization: Acme Corp", "Tool: syft"]

        assert _by_slug(_run(plugin, document, tmp_path))["creator-tool"] == "fail"

    def test_a_missing_creator_comment_fails(self, plugin, tmp_path):
        document = _conformant()
        document["creationInfo"]["creatorComment"] = ""

        assert _by_slug(_run(plugin, document, tmp_path))["creator-comment"] == "fail"

    @pytest.mark.parametrize("sbom_type", ["Design", "Source", "Build", "Analyzed", "Deployed", "Runtime"])
    def test_each_cisa_sbom_type_is_recognised(self, plugin, tmp_path, sbom_type):
        document = _conformant()
        document["creationInfo"]["creatorComment"] = f"SBOM Type: {sbom_type}"

        assert _by_slug(_run(plugin, document, tmp_path))["sbom-type"] == "pass"

    def test_a_comment_without_an_sbom_type_fails(self, plugin, tmp_path):
        document = _conformant()
        document["creationInfo"]["creatorComment"] = "Generated nightly."

        assert _by_slug(_run(plugin, document, tmp_path))["sbom-type"] == "fail"


class TestUnreadableInput:
    def test_invalid_json_is_an_error_not_a_verdict(self, plugin, tmp_path):
        """An unreadable document cannot be judged conformant or not."""
        path = tmp_path / "sbom.json"
        path.write_text("{not json", encoding="utf-8")

        result = plugin.assess("sbom-1", path)

        assert result.summary.error_count == 1
        assert result.summary.fail_count == 0


def test_metadata_matches_the_registered_name():
    """The registry entry and the plugin must agree, or the orchestrator
    cannot load it."""
    metadata = OpenChainTelcoPlugin().get_metadata()

    assert metadata.name == "openchain-telco-1.1"
    assert metadata.category.value == "compliance"


class TestMalformedInput:
    """A non-conformant document must be reported, not crash the assessment."""

    def test_a_non_dict_creation_info_does_not_crash(self, plugin, tmp_path):
        document = _conformant() | {"creationInfo": "not an object"}

        result = _run(plugin, document, tmp_path)

        statuses = _by_slug(result)
        assert statuses["creator"] == "fail"
        assert statuses["created"] == "fail"
        assert result.summary.error_count == 0

    def test_a_null_creation_info_does_not_crash(self, plugin, tmp_path):
        document = _conformant() | {"creationInfo": None}

        assert _by_slug(_run(plugin, document, tmp_path))["creator"] == "fail"


class TestRemediationPointsAtTheRightPlace:
    def test_top_level_fields_are_named_as_top_level(self, plugin, tmp_path):
        """Most §3.2 document elements are top-level keys; only Creator and
        Created live under creationInfo."""
        document = _conformant()
        del document["dataLicense"]

        result = _run(plugin, document, tmp_path)
        finding = next(f for f in result.findings if f.id.endswith("data-license"))

        assert "top-level" in finding.remediation

    def test_creation_info_fields_are_named_as_such(self, plugin, tmp_path):
        document = _conformant()
        document["creationInfo"]["creators"] = []

        result = _run(plugin, document, tmp_path)
        finding = next(f for f in result.findings if f.id.endswith(":creator"))

        assert "document creation information" in finding.remediation
