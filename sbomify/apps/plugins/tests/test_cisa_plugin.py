"""The CISA 2026 minimum elements, scored against all three document shapes.

Organised around what the standard asks for rather than around the code: one
class per behaviour, and the cases that would have passed under the 2025
draft implementation are called out where they are the point of the test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sbomify.apps.plugins.builtins.cisa import CISAMinimumElementsPlugin
from sbomify.apps.plugins.sdk.base import SBOMContext

ALL_ELEMENTS = CISAMinimumElementsPlugin.METADATA_ELEMENTS + CISAMinimumElementsPlugin.COMPONENT_ELEMENTS


@pytest.fixture
def plugin() -> CISAMinimumElementsPlugin:
    return CISAMinimumElementsPlugin()


def assess(plugin: CISAMinimumElementsPlugin, tmp_path: Path, document: dict, context: Any = None) -> dict[str, str]:
    """Score a document and return element key to status."""
    path = tmp_path / "sbom.json"
    path.write_text(json.dumps(document))
    result = plugin.assess("sbom-1", path, context=context)
    return {finding.metadata["element"]: finding.status for finding in result.findings}


def detail(plugin: CISAMinimumElementsPlugin, tmp_path: Path, document: dict, element: str) -> str:
    """The description one element reported, for asserting on what a reader is told."""
    path = tmp_path / "sbom.json"
    path.write_text(json.dumps(document))
    result = plugin.assess("sbom-1", path)
    return next(f.description for f in result.findings if f.metadata.get("element") == element)


def cyclonedx(**overrides: Any) -> dict:
    """A CycloneDX document that satisfies every element, before overrides."""
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "timestamp": "2026-07-29T10:00:00Z",
            "authors": [{"name": "Acme Release Engineering"}],
            "lifecycles": [{"phase": "build"}],
            "tools": {"components": [{"name": "syft", "version": "1.51.1"}]},
        },
        "components": [
            {
                "name": "openssl",
                "version": "3.0.11",
                "type": "library",
                "manufacturer": {"name": "The OpenSSL Project"},
                "purl": "pkg:generic/openssl@3.0.11",
                "hashes": [{"alg": "SHA-256", "content": "a" * 64}],
                "licenses": [{"license": {"id": "Apache-2.0"}}],
            },
            {
                "name": "zlib",
                "version": "1.3",
                "type": "library",
                "manufacturer": {"name": "Zlib"},
                "purl": "pkg:generic/zlib@1.3",
                "hashes": [{"alg": "SHA-256", "content": "b" * 64}],
                "licenses": [{"license": {"id": "Zlib"}}],
            },
        ],
        "dependencies": [{"ref": "openssl", "dependsOn": ["zlib"]}],
        "signature": {"algorithm": "RS512", "value": "signed"},
    }
    document.update(overrides)
    return document


def spdx2(**overrides: Any) -> dict:
    """An SPDX 2.3 document that satisfies every element, before overrides."""
    document = {
        "spdxVersion": "SPDX-2.3",
        "SPDXID": "SPDXRef-DOCUMENT",
        "documentNamespace": "https://acme.example/spdx/image-2026-07-29",
        "creationInfo": {
            "created": "2026-07-29T10:00:00Z",
            "creators": ["Organization: Acme Inc", "Tool: syft-1.51.1"],
            "comment": "Generated after build from the release image.",
        },
        "packages": [
            {
                "name": "openssl",
                "SPDXID": "SPDXRef-openssl",
                "versionInfo": "3.0.11",
                "originator": "Organization: The OpenSSL Project",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": "pkg:generic/openssl@3.0.11",
                    }
                ],
                "checksums": [{"algorithm": "SHA256", "checksumValue": "a" * 64}],
                "licenseDeclared": "Apache-2.0",
            },
            {
                "name": "zlib",
                "SPDXID": "SPDXRef-zlib",
                "versionInfo": "1.3",
                "originator": "Organization: Zlib",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": "pkg:generic/zlib@1.3",
                    }
                ],
                "checksums": [{"algorithm": "SHA256", "checksumValue": "b" * 64}],
                "licenseDeclared": "Zlib",
            },
        ],
        "relationships": [
            {"spdxElementId": "SPDXRef-openssl", "relationshipType": "DEPENDS_ON", "relatedSpdxElement": "SPDXRef-zlib"}
        ],
    }
    document.update(overrides)
    return document


def spdx3(**overrides: Any) -> dict:
    """An SPDX 3.0.1 document that satisfies every element, before overrides."""
    graph: list[dict[str, Any]] = [
        {"type": "SpdxDocument", "spdxId": "urn:doc", "name": "image"},
        {"type": "software_Sbom", "spdxId": "urn:sbom", "software_sbomType": "build"},
        {"type": "Organization", "spdxId": "urn:org:acme", "name": "Acme Inc"},
        {"type": "Organization", "spdxId": "urn:org:openssl", "name": "The OpenSSL Project"},
        {"type": "Tool", "spdxId": "urn:tool:syft", "name": "syft", "software_packageVersion": "1.51.1"},
        {
            "type": "CreationInfo",
            "spdxId": "urn:ci",
            "specVersion": "3.0.1",
            "created": "2026-07-29T10:00:00Z",
            "createdBy": ["urn:org:acme"],
            "createdUsing": ["urn:tool:syft"],
        },
        {
            "type": "software_Package",
            "spdxId": "urn:pkg:openssl",
            "name": "openssl",
            "software_packageVersion": "3.0.11",
            "software_packageUrl": "pkg:generic/openssl@3.0.11",
            "originatedBy": ["urn:org:openssl"],
            "verifiedUsing": [{"type": "Hash", "algorithm": "sha256", "hashValue": "a" * 64}],
        },
        {
            "type": "software_Package",
            "spdxId": "urn:pkg:zlib",
            "name": "zlib",
            "software_packageVersion": "1.3",
            "software_packageUrl": "pkg:generic/zlib@1.3",
            "originatedBy": ["urn:org:openssl"],
            "verifiedUsing": [{"type": "Hash", "algorithm": "sha256", "hashValue": "b" * 64}],
        },
        {
            "type": "Relationship",
            "spdxId": "urn:rel:lic1",
            "from": "urn:pkg:openssl",
            "relationshipType": "hasDeclaredLicense",
            "to": ["urn:lic:apache"],
        },
        {
            "type": "Relationship",
            "spdxId": "urn:rel:lic2",
            "from": "urn:pkg:zlib",
            "relationshipType": "hasDeclaredLicense",
            "to": ["urn:lic:zlib"],
        },
        {
            "type": "Relationship",
            "spdxId": "urn:rel:dep",
            "from": "urn:pkg:openssl",
            "relationshipType": "dependsOn",
            "to": ["urn:pkg:zlib"],
        },
    ]
    document: dict[str, Any] = {"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": graph}
    document.update(overrides)
    return document


SIGNED = SBOMContext(signature_blob_key="signatures/sbom-1.sig", signature_type="cosign-bundle")


class TestTheElementSet:
    def test_it_is_the_seventeen_data_fields(self, plugin: CISAMinimumElementsPlugin) -> None:
        """Nine about the document, eight about each component."""
        assert len(plugin.METADATA_ELEMENTS) == 9
        assert len(plugin.COMPONENT_ELEMENTS) == 8
        assert set(ALL_ELEMENTS) == set(plugin.ELEMENTS)

    def test_it_names_the_final_standard_and_not_the_draft(self, plugin: CISAMinimumElementsPlugin) -> None:
        assert plugin.get_metadata().name == "cisa-minimum-elements-2026"
        assert plugin.STANDARD_VERSION == "2026-07"
        assert "draft" not in plugin.STANDARD_NAME.lower()
        assert "2026" in plugin.STANDARD_URL

    @pytest.mark.parametrize("builder", [cyclonedx, spdx2, spdx3], ids=["cyclonedx", "spdx2", "spdx3"])
    def test_every_format_reports_every_element_once(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, builder: Any
    ) -> None:
        statuses = assess(plugin, tmp_path, builder())

        assert set(statuses) == set(ALL_ELEMENTS)

    @pytest.mark.parametrize("builder", [cyclonedx, spdx2, spdx3], ids=["cyclonedx", "spdx2", "spdx3"])
    def test_findings_come_back_in_the_order_the_standard_lists_them(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, builder: Any
    ) -> None:
        path = tmp_path / "sbom.json"
        path.write_text(json.dumps(builder()))

        emitted = [f.metadata["element"] for f in plugin.assess("s", path).findings]

        assert emitted == list(ALL_ELEMENTS)


class TestACompliantDocumentPasses:
    """The fixtures above are written to satisfy the standard, so they must."""

    @pytest.mark.parametrize("builder", [cyclonedx, spdx2, spdx3], ids=["cyclonedx", "spdx2", "spdx3"])
    def test_nothing_fails(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, builder: Any) -> None:
        statuses = assess(plugin, tmp_path, builder(), context=SIGNED)

        assert [element for element, status in statuses.items() if status != "pass"] == []


class TestTheAuthorIsNotTheTool:
    """CISA: the author "captures the entity operating the tool, not the tool itself"."""

    def test_spdx2_tool_only_creators_do_not_name_an_author(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        """The 2025 implementation passed this, because it only counted the list's length."""
        document = spdx2(creationInfo={"created": "2026-07-29T10:00:00Z", "creators": ["Tool: syft-1.51.1"]})

        statuses = assess(plugin, tmp_path, document)

        assert statuses["sbom_author"] == "fail"
        assert statuses["sbom_tool_name"] == "pass"

    def test_spdx2_junk_is_not_an_author_either(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        document = spdx2(creationInfo={"created": "2026-07-29T10:00:00Z", "creators": ["banana"]})

        assert assess(plugin, tmp_path, document)["sbom_author"] == "fail"

    @pytest.mark.parametrize("creator", ["Person: Jane Doe", "Organization: Acme Inc"])
    def test_spdx2_a_person_or_an_organization_is_an_author(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, creator: str
    ) -> None:
        document = spdx2(creationInfo={"created": "2026-07-29T10:00:00Z", "creators": [creator]})

        assert assess(plugin, tmp_path, document)["sbom_author"] == "pass"

    def test_spdx3_a_software_agent_is_the_tool_not_the_author(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        """SoftwareAgent sits in the shared agent map, so it used to satisfy the author."""
        document = spdx3()
        graph = [element for element in document["@graph"] if element["spdxId"] != "urn:org:acme"]
        graph.append({"type": "SoftwareAgent", "spdxId": "urn:agent:syft", "name": "syft"})
        for element in graph:
            if element.get("type") == "CreationInfo":
                element["createdBy"] = ["urn:agent:syft"]
        document["@graph"] = graph

        assert assess(plugin, tmp_path, document)["sbom_author"] == "fail"

    def test_cyclonedx_tools_alone_do_not_name_an_author(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        document = cyclonedx()
        document["metadata"].pop("authors")

        assert assess(plugin, tmp_path, document)["sbom_author"] == "fail"

    def test_cyclonedx_reads_the_manufacturer_as_an_author(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        document = cyclonedx()
        document["metadata"].pop("authors")
        document["metadata"]["manufacturer"] = {"name": "Acme Inc"}

        assert assess(plugin, tmp_path, document)["sbom_author"] == "pass"


class TestTheProducerIsWhoeverIsNamed:
    """The 2026 rename asks for the creator, so a document naming only the creator must not fail."""

    def test_spdx2_an_originator_alone_is_a_producer(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        """PackageOriginator is the producer, and the 2025 implementation never read it."""
        document = spdx2()
        for package in document["packages"]:
            package["originator"] = "Organization: The OpenSSL Project"
            package.pop("supplier", None)

        assert assess(plugin, tmp_path, document)["component_producer"] == "pass"

    def test_spdx2_a_supplier_alone_is_still_a_party(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        document = spdx2()
        for package in document["packages"]:
            package.pop("originator")
            package["supplier"] = "Organization: A Distributor"

        assert assess(plugin, tmp_path, document)["component_producer"] == "pass"

    def test_cyclonedx_a_manufacturer_alone_is_a_producer(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        """manufacturer is "the organization that created the component" and used to be ignored."""
        document = cyclonedx()
        for component in document["components"]:
            component["manufacturer"] = {"name": "The OpenSSL Project"}
            component.pop("publisher", None)
            component.pop("supplier", None)

        assert assess(plugin, tmp_path, document)["component_producer"] == "pass"

    def test_naming_nobody_fails(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        document = cyclonedx()
        for component in document["components"]:
            component.pop("manufacturer")

        statuses = assess(plugin, tmp_path, document)
        assert statuses["component_producer"] == "fail"

    def test_spdx3_a_dangling_reference_names_nobody(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        """originatedBy pointing at an element that is not in the graph is not a name."""
        document = spdx3()
        for element in document["@graph"]:
            if element["type"] == "software_Package":
                element["originatedBy"] = ["urn:org:missing"]

        assert assess(plugin, tmp_path, document)["component_producer"] == "fail"

    def test_spdx3_noassertion_still_reaches_the_unknown_outcome(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        """It arrives as a bare string, on the same path a dangling reference takes."""
        document = spdx3()
        for element in document["@graph"]:
            if element["type"] == "software_Package":
                element["originatedBy"] = ["NOASSERTION"]

        assert assess(plugin, tmp_path, document)["component_producer"] == "warning"


class TestTheTimestampIsRfc9557:
    @pytest.mark.parametrize(
        "stamp",
        [
            "2026-07-29T10:00:00Z",
            "2026-07-29T10:00:00.123Z",
            "2026-07-29T10:00:00+02:00",
            "2026-07-29T10:00:00Z[Europe/Berlin]",
            "2026-07-29T10:00:00+01:00[Europe/London][u-ca=hebrew]",
        ],
    )
    def test_accepted(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, stamp: str) -> None:
        document = cyclonedx()
        document["metadata"]["timestamp"] = stamp

        assert assess(plugin, tmp_path, document)["sbom_timestamp"] == "pass"

    @pytest.mark.parametrize(
        "stamp",
        [
            "2026-07-29",  # a bare date, which fromisoformat used to accept
            "2026-07-29 10:00:00Z",  # a space separator, likewise
            "2026-07-29T10:00:00",  # no offset at all
            "2026-02-30T10:00:00Z",  # right shape, impossible date
            "not a timestamp",
            "",
        ],
    )
    def test_refused(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, stamp: str) -> None:
        document = cyclonedx()
        document["metadata"]["timestamp"] = stamp

        assert assess(plugin, tmp_path, document)["sbom_timestamp"] == "fail"


class TestTheIdentifiersCisaNames:
    """CISA adds the intrinsic identifiers OmniBOR and SWHID to CPE and PURL."""

    @pytest.mark.parametrize("field_name", ["purl", "cpe", "swid", "omniborId", "swhid"])
    def test_cyclonedx_accepts_each(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, field_name: str) -> None:
        document = cyclonedx()
        for component in document["components"]:
            component.pop("purl")
            component[field_name] = "identifier-value"

        assert assess(plugin, tmp_path, document)["component_identifiers"] == "pass"

    @pytest.mark.parametrize("reference_type", ["purl", "cpe23Type", "cpe22Type", "swid", "gitoid", "swhid"])
    def test_spdx2_accepts_each(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, reference_type: str) -> None:
        document = spdx2()
        for package in document["packages"]:
            package["externalRefs"] = [
                {"referenceCategory": "OTHER", "referenceType": reference_type, "referenceLocator": "value"}
            ]

        assert assess(plugin, tmp_path, document)["component_identifiers"] == "pass"

    def test_a_reference_that_is_not_an_identifier_does_not_count(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        document = spdx2()
        for package in document["packages"]:
            package["externalRefs"] = [
                {"referenceCategory": "OTHER", "referenceType": "website", "referenceLocator": "https://example.com"}
            ]

        assert assess(plugin, tmp_path, document)["component_identifiers"] == "fail"


class TestTheLicenceTheProducerDeclares:
    def test_spdx3_accepts_a_declared_licence(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        """hasDeclaredLicense is what the producer declares, and it used to fail."""
        statuses = assess(plugin, tmp_path, spdx3())

        assert statuses["component_license"] == "pass"

    def test_spdx3_accepts_a_concluded_licence(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        document = spdx3()
        for element in document["@graph"]:
            if element.get("relationshipType") == "hasDeclaredLicense":
                element["relationshipType"] = "hasConcludedLicense"

        assert assess(plugin, tmp_path, document)["component_license"] == "pass"

    def test_spdx3_no_licence_relationship_fails(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        document = spdx3()
        document["@graph"] = [
            element for element in document["@graph"] if "License" not in str(element.get("relationshipType"))
        ]

        assert assess(plugin, tmp_path, document)["component_license"] == "fail"


class TestTheGenerationContext:
    @pytest.mark.parametrize("phase", ["build", "post-build", "design", "operations"])
    def test_cyclonedx_lifecycle_phases_are_accepted(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, phase: str
    ) -> None:
        document = cyclonedx()
        document["metadata"]["lifecycles"] = [{"phase": phase}]

        assert assess(plugin, tmp_path, document)["sbom_generation_context"] == "pass"

    @pytest.mark.parametrize("wording", ["after build", "after_build", "before build", "during build"])
    def test_cisas_own_wording_is_accepted(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, wording: str
    ) -> None:
        """The standard writes "before build", "build" and "after build"; the draft set rejected them."""
        document = spdx2()
        document["creationInfo"]["comment"] = f"Generated {wording}."

        assert assess(plugin, tmp_path, document)["sbom_generation_context"] == "pass"

    def test_a_custom_cyclonedx_lifecycle_counts(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        """The spec allows a named lifecycle instead of a phase, and CISA accepts more specific identifiers."""
        document = cyclonedx()
        document["metadata"]["lifecycles"] = [{"name": "nightly image bake", "description": "after the build step"}]

        assert assess(plugin, tmp_path, document)["sbom_generation_context"] == "pass"

    @pytest.mark.parametrize("sbom_type", ["build", "source", "analyzed", "deployed", "runtime", "design"])
    def test_spdx3_accepts_the_specs_own_vocabulary(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, sbom_type: str
    ) -> None:
        document = spdx3()
        for element in document["@graph"]:
            if element.get("type") == "software_Sbom":
                element["software_sbomType"] = sbom_type

        assert assess(plugin, tmp_path, document)["sbom_generation_context"] == "pass"

    def test_spdx3_refuses_a_value_the_spec_does_not_define(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        """Non-emptiness used to be the whole test, so "banana" scored as a stated phase."""
        document = spdx3()
        for element in document["@graph"]:
            if element.get("type") == "software_Sbom":
                element["software_sbomType"] = "banana"

        assert assess(plugin, tmp_path, document)["sbom_generation_context"] == "fail"


class TestDeclaredUnknownIsItsOwnOutcome:
    """The standard asks an author without a value to say so, so saying so is not a miss."""

    @pytest.mark.parametrize(
        ("element", "field_name"),
        [("component_version", "versionInfo"), ("component_producer", "originator")],
    )
    def test_spdx2_noassertion_warns_rather_than_failing(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, element: str, field_name: str
    ) -> None:
        document = spdx2()
        for package in document["packages"]:
            package[field_name] = "NOASSERTION"

        assert assess(plugin, tmp_path, document)[element] == "warning"

    def test_spdx2_an_omission_still_fails(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        document = spdx2()
        for package in document["packages"]:
            package.pop("versionInfo")

        assert assess(plugin, tmp_path, document)["component_version"] == "fail"

    def test_none_is_an_answer_and_not_an_unknown(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        """SPDX NONE says there is none, which is a determination the author made."""
        document = spdx2()
        for package in document["packages"]:
            package["licenseDeclared"] = "NONE"

        assert assess(plugin, tmp_path, document)["component_license"] == "pass"

    def test_a_miss_outranks_a_declared_unknown(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        """One package saying nothing is the more serious outcome, so it is the one reported."""
        document = spdx2()
        document["packages"][0]["versionInfo"] = "NOASSERTION"
        document["packages"][1].pop("versionInfo")

        assert assess(plugin, tmp_path, document)["component_version"] == "fail"

    def test_the_finding_names_which_components_said_unknown(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        document = spdx2()
        document["packages"][0]["versionInfo"] = "NOASSERTION"
        document["packages"][1]["versionInfo"] = "NOASSERTION"

        assert "openssl" in detail(plugin, tmp_path, document, "component_version")


class TestWhatAReaderIsTold:
    def test_a_declared_unknown_does_not_borrow_the_absence_wording(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        """ "Named without a version" describes the wrong document when it said unknown."""
        document = spdx2(
            creationInfo={"created": "2026-07-29T10:00:00Z", "creators": ["Tool: NOASSERTION"]},
        )

        statuses = assess(plugin, tmp_path, document)
        told = detail(plugin, tmp_path, document, "sbom_tool_version")

        assert statuses["sbom_tool_version"] == "warning"
        assert "states this is unknown" in told
        assert "without a version" not in told


class TestEveryFormatAgreesOnAnUnknown:
    def test_spdx3_tool_version_warns_like_the_other_two(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        """An element that warns on one format and fails on another for the same document is a bug."""
        document = spdx3()
        for element in document["@graph"]:
            if element.get("type") == "Tool":
                element["software_packageVersion"] = "NOASSERTION"

        assert assess(plugin, tmp_path, document)["sbom_tool_version"] == "warning"

    def test_an_unreadable_document_still_reports_the_format_key(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        """The error path carries the same metadata keys, so a consumer need not branch."""
        path = tmp_path / "sbom.json"
        path.write_text(json.dumps({"hello": "world"}))

        result = plugin.assess("s", path)

        assert result.metadata["sbom_format"] == "unknown"
        assert set(result.metadata) >= {"standard_name", "standard_version", "standard_url", "sbom_format"}


class TestTheSignature:
    def test_cyclonedx_carries_its_own(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        assert assess(plugin, tmp_path, cyclonedx())["sbom_author_signature"] == "pass"

    def test_a_stored_signature_satisfies_a_format_that_cannot_carry_one(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        """SPDX has no in-document signature, and CISA points at existing signing infrastructure."""
        assert assess(plugin, tmp_path, spdx2(), context=SIGNED)["sbom_author_signature"] == "pass"

    def test_unsigned_spdx_fails_and_says_why(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        statuses = assess(plugin, tmp_path, spdx2())

        assert statuses["sbom_author_signature"] == "fail"
        assert "no in-document signature" in detail(plugin, tmp_path, spdx2(), "sbom_author_signature")


class TestTheNewMetadataElements:
    def test_the_format_names_itself(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        statuses = assess(plugin, tmp_path, cyclonedx())

        assert statuses["sbom_data_format_name"] == "pass"
        assert statuses["sbom_data_format_version"] == "pass"

    def test_a_missing_spec_version_fails(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        document = cyclonedx()
        document.pop("specVersion")

        assert assess(plugin, tmp_path, document)["sbom_data_format_version"] == "fail"

    def test_the_tool_version_is_read_from_the_spdx_naming_convention(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        """SPDX 2.x has no tool version field, so the version rides the name."""
        assert assess(plugin, tmp_path, spdx2())["sbom_tool_version"] == "pass"

        document = spdx2(creationInfo={"created": "2026-07-29T10:00:00Z", "creators": ["Tool: syft"]})
        assert assess(plugin, tmp_path, document)["sbom_tool_version"] == "fail"

    def test_the_document_version(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        assert assess(plugin, tmp_path, cyclonedx())["sbom_version"] == "pass"

        document = cyclonedx()
        document.pop("version")
        assert assess(plugin, tmp_path, document)["sbom_version"] == "fail"

    def test_spdx_uses_its_namespace_to_tell_revisions_apart(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        assert assess(plugin, tmp_path, spdx2())["sbom_version"] == "pass"

        document = spdx2()
        document.pop("documentNamespace")
        assert assess(plugin, tmp_path, document)["sbom_version"] == "fail"


class TestTheHashSplitsInTwo:
    def test_both_are_reported(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        statuses = assess(plugin, tmp_path, cyclonedx())

        assert statuses["component_hash_value"] == "pass"
        assert statuses["component_hash_algorithm"] == "pass"

    def test_a_value_without_a_recognised_algorithm_splits_the_two(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        """CISA asks for the algorithm by an IANA name so the hash can be checked."""
        document = cyclonedx()
        for component in document["components"]:
            component["hashes"] = [{"alg": "homegrown", "content": "a" * 64}]

        statuses = assess(plugin, tmp_path, document)
        assert statuses["component_hash_value"] == "pass"
        assert statuses["component_hash_algorithm"] == "fail"

    @pytest.mark.parametrize("algorithm", ["SHA-256", "SHA256", "sha256", "SHA3-512", "BLAKE2b-512"])
    def test_the_spellings_the_formats_disagree_about_are_all_read(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, algorithm: str
    ) -> None:
        document = cyclonedx()
        for component in document["components"]:
            component["hashes"] = [{"alg": algorithm, "content": "a" * 64}]

        assert assess(plugin, tmp_path, document)["component_hash_algorithm"] == "pass"


class TestWhatCountsAsAComponent:
    def test_the_target_component_is_assessed_too(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        """CISA covers "the target component ... and all subcomponents"."""
        document = cyclonedx()
        document["metadata"]["component"] = {"name": "image", "type": "application"}

        assert assess(plugin, tmp_path, document)["component_version"] == "fail"

    def test_nested_components_are_assessed(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        document = cyclonedx()
        document["components"][0]["components"] = [{"name": "nested", "type": "library"}]

        assert assess(plugin, tmp_path, document)["component_version"] == "fail"

    def test_a_file_entry_is_not_a_component(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        """A lockfile is input metadata, so the per-component fields do not describe it."""
        document = cyclonedx()
        document["components"].append({"name": "uv.lock", "type": "file"})

        statuses = assess(plugin, tmp_path, document)
        assert statuses["component_version"] == "pass"
        assert statuses["component_name"] == "pass"

    def test_a_document_with_no_components_warns_rather_than_passing(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        document = cyclonedx(components=[], dependencies=[])

        statuses = assess(plugin, tmp_path, document)
        assert statuses["component_name"] == "warning"
        assert statuses["component_version"] == "warning"


class TestDependencyRelationships:
    def test_an_edge_is_required_once_there_is_more_than_one_component(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        document = cyclonedx()
        document["dependencies"] = [{"ref": "openssl", "dependsOn": []}]

        assert assess(plugin, tmp_path, document)["component_dependency_relationship"] == "fail"

    def test_a_single_component_has_nothing_to_relate(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        document = cyclonedx()
        document["components"] = document["components"][:1]
        document["dependencies"] = []

        assert assess(plugin, tmp_path, document)["component_dependency_relationship"] == "pass"

    def test_spdx2_reads_its_relationship_vocabulary(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        document = spdx2()
        document["relationships"] = [
            {"spdxElementId": "SPDXRef-openssl", "relationshipType": "CONTAINS", "relatedSpdxElement": "SPDXRef-zlib"}
        ]

        assert assess(plugin, tmp_path, document)["component_dependency_relationship"] == "pass"

    def test_file_entries_do_not_make_an_edge_necessary(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        """One shipped component plus a lockfile still has nothing to relate."""
        document = cyclonedx()
        document["components"] = document["components"][:1]
        document["components"].append({"name": "uv.lock", "type": "file"})
        document["dependencies"] = []

        assert assess(plugin, tmp_path, document)["component_dependency_relationship"] == "pass"

    def test_spdx2_file_packages_do_not_make_an_edge_necessary(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        document = spdx2()
        document["packages"] = document["packages"][:1]
        document["packages"].append({"name": "uv.lock", "SPDXID": "SPDXRef-File-uv-lock"})
        document["relationships"] = []

        assert assess(plugin, tmp_path, document)["component_dependency_relationship"] == "pass"


class TestMalformedInput:
    def test_a_document_that_is_not_json_is_an_error(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        path = tmp_path / "sbom.json"
        path.write_text("{not json")

        result = plugin.assess("s", path)

        assert result.summary.error_count == 1
        assert result.findings[0].status == "error"

    def test_the_error_metadata_is_the_flag_every_other_plugin_sets(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path
    ) -> None:
        """The component page reads the flag and takes the message off the finding."""
        path = tmp_path / "sbom.json"
        path.write_text("{not json")

        result = plugin.assess("s", path)

        assert result.metadata["error"] is True
        assert result.findings[0].description

    def test_json_that_is_not_an_object_is_an_error(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        path = tmp_path / "sbom.json"
        path.write_text("[]")

        assert plugin.assess("s", path).summary.error_count == 1

    def test_a_format_we_do_not_recognise_is_an_error(self, plugin: CISAMinimumElementsPlugin, tmp_path: Path) -> None:
        path = tmp_path / "sbom.json"
        path.write_text(json.dumps({"hello": "world"}))

        assert plugin.assess("s", path).summary.error_count == 1

    @pytest.mark.parametrize("junk", [None, 5, "text", {"a": 1}])
    def test_a_field_of_the_wrong_type_does_not_crash_the_run(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, junk: Any
    ) -> None:
        """Uploads are untrusted, so a wrong type is a finding rather than a traceback."""
        document = cyclonedx(components=junk, dependencies=junk, metadata=junk)

        statuses = assess(plugin, tmp_path, document)

        assert set(statuses) == set(ALL_ELEMENTS)

    @pytest.mark.parametrize("junk", [None, 5, "text"])
    def test_a_malformed_spdx3_graph_does_not_crash_the_run(
        self, plugin: CISAMinimumElementsPlugin, tmp_path: Path, junk: Any
    ) -> None:
        document = {"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": junk}
        path = tmp_path / "sbom.json"
        path.write_text(json.dumps(document))

        result = plugin.assess("s", path)

        assert result.summary.error_count in (0, 1)
