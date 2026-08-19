"""A conformant SPDX 3.0.1 document must not score worse than a malformed one.

The shared helpers read three things wrongly, and every plugin inherits all
three:

- ``externalIdentifiers`` (plural) where the spec property is
  ``externalIdentifier``, and ``packageURL`` where the vocabulary value is
  ``packageUrl`` — so a spec-conformant purl is invisible while the non-spec
  spelling passes.
- ``software_packageUrl``, the first-class purl property 3.0.1 added, is read
  nowhere.
- an inline Agent object in ``createdBy``/``originatedBy`` (legal per
  ``Agent_derived``) is passed to ``dict.get`` as a key and raises
  ``TypeError: unhashable type``, failing the whole assessment run.
- a supplier typed ``SoftwareAgent`` or bare ``Agent`` is routed to the wrong
  bucket (or none), so the package scores as having no supplier.

The legacy spellings stay accepted throughout: stored artifacts carry them.
"""

from __future__ import annotations

from typing import Any

from sbomify.apps.plugins.builtins._spdx3_helpers import (
    extract_spdx3_elements,
    get_spdx3_creation_info_fields,
    get_spdx3_package_fields,
    has_spdx3_supplier,
    resolve_spdx3_agent,
    spdx3_package_purl,
)
from sbomify.apps.plugins.builtins.bsi import BSICompliancePlugin


def _graph(*elements: dict[str, Any]) -> dict[str, Any]:
    return {"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": list(elements)}


class TestAgentRouting:
    """Element routing: every Agent subtype is a resolvable agent."""

    def _agents_for(self, elem_type: str) -> dict[str, dict[str, Any]]:
        doc = _graph({"type": elem_type, "spdxId": "urn:agent", "name": "ACME"})
        _, _, _, agents, _ = extract_spdx3_elements(doc)
        return agents

    def test_person_and_organization_still_route(self) -> None:
        assert self._agents_for("Person")["urn:agent"]["name"] == "ACME"
        assert self._agents_for("Organization")["urn:agent"]["name"] == "ACME"

    def test_software_agent_is_an_agent(self) -> None:
        assert self._agents_for("SoftwareAgent")["urn:agent"]["name"] == "ACME"

    def test_bare_agent_is_an_agent(self) -> None:
        """The type the current router drops on the floor."""
        assert self._agents_for("Agent")["urn:agent"]["name"] == "ACME"

    def test_tool_stays_a_tool(self) -> None:
        doc = _graph({"type": "Tool", "spdxId": "urn:t", "name": "syft"})
        _, _, _, agents, tools = extract_spdx3_elements(doc)
        assert tools["urn:t"]["name"] == "syft"
        assert "urn:t" not in agents

    def test_software_agent_in_created_using_still_resolves(self) -> None:
        """A SoftwareAgent now lives in the agents map, and the tool lookup
        must find it there — otherwise sbomify-action detection breaks."""
        doc = _graph(
            {"type": "SoftwareAgent", "spdxId": "urn:sa", "name": "sbomify-action-1.0"},
            {"type": "CreationInfo", "spdxId": "urn:ci", "createdUsing": ["urn:sa"]},
        )
        creation_info, _, _, agents, tools = extract_spdx3_elements(doc)

        fields = get_spdx3_creation_info_fields(creation_info, agents, tools)

        assert "sbomify-action-1.0" in fields["tool_entries"]


class TestResolveAgent:
    AGENTS = {"urn:org": {"type": "Organization", "name": "ACME"}}

    def test_string_ref_resolves_through_the_map(self) -> None:
        assert resolve_spdx3_agent("urn:org", self.AGENTS)["name"] == "ACME"

    def test_inline_dict_passes_through(self) -> None:
        inline = {"type": "Organization", "name": "Inline Corp"}
        assert resolve_spdx3_agent(inline, self.AGENTS) is inline

    def test_spdx_organization_literal_is_the_spdx_agent(self) -> None:
        assert resolve_spdx3_agent("SpdxOrganization", self.AGENTS)["name"] == "SPDX"

    def test_unknown_ref_is_empty(self) -> None:
        assert resolve_spdx3_agent("urn:missing", self.AGENTS) == {}
        assert resolve_spdx3_agent(None, self.AGENTS) == {}

    def test_inline_agent_in_created_by_does_not_crash(self) -> None:
        """The reported failure: dict used as a dict key → TypeError →
        the orchestrator marks the whole run FAILED."""
        creation_info = {
            "type": "CreationInfo",
            "createdBy": [{"type": "Organization", "name": "Inline Corp"}],
        }

        fields = get_spdx3_creation_info_fields(creation_info, {})

        assert "Inline Corp" in fields["creators"]


class TestSpecFieldNames:
    """#1325: the three spellings of a purl, all of which must count."""

    def test_software_package_url_alone_is_a_unique_id(self) -> None:
        package = {"type": "software_Package", "name": "p", "software_packageUrl": "pkg:pypi/p@1.0"}

        fields = get_spdx3_package_fields(package)

        assert fields["has_unique_id"] is True
        assert spdx3_package_purl(package) == "pkg:pypi/p@1.0"

    def test_singular_external_identifier_with_spec_casing(self) -> None:
        package = {
            "type": "software_Package",
            "name": "p",
            "externalIdentifier": [{"externalIdentifierType": "packageUrl", "identifier": "pkg:pypi/p@1.0"}],
        }

        fields = get_spdx3_package_fields(package)

        assert fields["has_unique_id"] is True
        assert spdx3_package_purl(package) == "pkg:pypi/p@1.0"

    def test_legacy_plural_and_uppercase_still_accepted(self) -> None:
        """Stored artifacts carry the old spelling; they must not regress."""
        package = {
            "type": "software_Package",
            "name": "p",
            "externalIdentifiers": [{"externalIdentifierType": "packageURL", "identifier": "pkg:pypi/p@1.0"}],
        }

        assert get_spdx3_package_fields(package)["has_unique_id"] is True
        assert spdx3_package_purl(package) == "pkg:pypi/p@1.0"

    def test_purl_type_variant_accepted(self) -> None:
        package = {
            "type": "software_Package",
            "name": "p",
            "externalIdentifier": [{"externalIdentifierType": "purl", "identifier": "pkg:pypi/p@1.0"}],
        }

        assert get_spdx3_package_fields(package)["has_unique_id"] is True

    def test_no_identifier_still_fails(self) -> None:
        assert get_spdx3_package_fields({"type": "software_Package", "name": "p"})["has_unique_id"] is False
        assert spdx3_package_purl({"type": "software_Package", "name": "p"}) is None

    def test_creator_email_via_singular_external_identifier(self) -> None:
        creation_info = {"type": "CreationInfo", "createdBy": ["urn:p"]}
        agents = {
            "urn:p": {
                "type": "Person",
                "name": "Jane",
                "externalIdentifier": [{"externalIdentifierType": "email", "identifier": "jane@acme.test"}],
            }
        }

        fields = get_spdx3_creation_info_fields(creation_info, agents)

        assert "jane@acme.test" in fields["creators"]


class TestSupplierResolution:
    """The consumer loop shared by NTIA, CISA and FDA, extracted."""

    def test_string_ref_to_known_agent(self) -> None:
        assert has_spdx3_supplier(["urn:org"], {"urn:org": {"name": "ACME"}}) is True

    def test_inline_agent_dict_counts(self) -> None:
        assert has_spdx3_supplier([{"type": "Organization", "name": "Inline"}], {}) is True

    def test_unknown_ref_does_not(self) -> None:
        assert has_spdx3_supplier(["urn:nope"], {}) is False
        assert has_spdx3_supplier([], {"urn:org": {"name": "ACME"}}) is False


class TestBSICreatorMethods:
    """BSI's private copies crash and misread the same way the helpers did."""

    def _plugin(self) -> BSICompliancePlugin:
        return BSICompliancePlugin()

    def test_inline_agent_in_created_by_does_not_crash(self) -> None:
        creation_info = {
            "type": "CreationInfo",
            "createdBy": [
                {
                    "type": "Organization",
                    "name": "Inline",
                    "externalIdentifier": [{"externalIdentifierType": "email", "identifier": "sec@inline.test"}],
                }
            ],
        }

        creator = self._plugin()._get_spdx3_sbom_creator(creation_info, {})

        assert creator == "sec@inline.test"

    def test_inline_agent_in_originated_by_reads_the_supplier(self) -> None:
        package = {
            "type": "software_Package",
            "name": "p",
            "originatedBy": [
                {
                    "type": "SoftwareAgent",
                    "name": "builder",
                    "externalIdentifier": [{"externalIdentifierType": "email", "identifier": "bot@acme.test"}],
                }
            ],
        }

        creator = self._plugin()._get_spdx3_component_creator(package, {})

        assert creator == "bot@acme.test"

    def test_identifier_check_accepts_spec_spelling(self) -> None:
        package = {
            "type": "software_Package",
            "name": "p",
            "externalIdentifier": [{"externalIdentifierType": "packageUrl", "identifier": "pkg:pypi/p@1"}],
        }

        assert self._plugin()._has_spdx3_identifier(package) is True

    def test_identifier_check_keeps_legacy_spelling(self) -> None:
        package = {
            "type": "software_Package",
            "name": "p",
            "externalIdentifiers": [{"externalIdentifierType": "packageURL", "identifier": "pkg:pypi/p@1"}],
        }

        assert self._plugin()._has_spdx3_identifier(package) is True


class TestSPDX3PackageSchemaPurl:
    """The third copy of the purl read, in sboms/schemas.py."""

    def test_purl_from_software_package_url(self) -> None:
        from sbomify.apps.sboms.schemas import SPDX3Package

        package = SPDX3Package.model_validate(
            {"name": "p", "software_packageVersion": "1.0", "software_packageUrl": "pkg:pypi/p@1.0"}
        )

        assert package.purl == "pkg:pypi/p@1.0"

    def test_purl_from_singular_spec_identifier(self) -> None:
        from sbomify.apps.sboms.schemas import SPDX3Package

        package = SPDX3Package.model_validate(
            {
                "name": "p",
                "software_packageVersion": "1.0",
                "externalIdentifier": [{"externalIdentifierType": "packageUrl", "identifier": "pkg:pypi/p@1.0"}],
            }
        )

        assert package.purl == "pkg:pypi/p@1.0"

    def test_legacy_read_and_fallback_unchanged(self) -> None:
        from sbomify.apps.sboms.schemas import SPDX3Package

        legacy = SPDX3Package.model_validate(
            {
                "name": "p",
                "software_packageVersion": "1.0",
                "externalIdentifiers": [{"externalIdentifierType": "packageURL", "identifier": "pkg:pypi/p@1.0"}],
            }
        )
        bare = SPDX3Package.model_validate({"name": "p", "software_packageVersion": "1.0"})

        assert legacy.purl == "pkg:pypi/p@1.0"
        assert bare.purl == "pkg:/p@1.0"


class TestHostileGraphEntries:
    """Untrusted documents: a non-dict element or a null type must be skipped,
    not crash the extraction."""

    def test_non_dict_and_null_type_entries_are_skipped(self) -> None:
        doc = _graph(
            {"type": None, "spdxId": "urn:x"},
            {"type": "Person", "spdxId": "urn:p", "name": "Jane"},
        )
        doc["@graph"].insert(0, "not-an-element")
        doc["@graph"].insert(0, 42)

        _, _, _, agents, _ = extract_spdx3_elements(doc)

        assert agents["urn:p"]["name"] == "Jane"

    def test_null_graph_yields_empty_extraction(self) -> None:
        creation_info, packages, relationships, agents, tools = extract_spdx3_elements({"@graph": None})

        assert creation_info is None
        assert packages == [] and relationships == [] and agents == {} and tools == {}
