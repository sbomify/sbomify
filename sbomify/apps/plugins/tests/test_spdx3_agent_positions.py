"""Every legal shape a set-valued SPDX 3 property can take, read the same way.

``createdBy``, ``originatedBy``, ``suppliedBy`` and ``createdUsing`` are all
sets in the 3.0.1 schema. JSON-LD compact form serialises a one-element set as
a bare string or a bare object, so the same document is conformant written
either way, and a reader that only iterates lists silently finds nobody.
"""

from __future__ import annotations

import pytest

from sbomify.apps.plugins.builtins._spdx3_helpers import spdx3_refs
from sbomify.apps.plugins.builtins._spdx3_helpers import (
    get_spdx3_creation_info_fields,
    get_spdx3_package_fields,
    has_spdx3_supplier,
)
from sbomify.apps.plugins.builtins.bsi import BSICompliancePlugin

EMAIL = "releases@acme.test"
URL = "https://acme.test/security"

_ACME = {
    "type": "Organization",
    "spdxId": "urn:acme",
    "name": "Acme",
    "externalIdentifier": [{"externalIdentifierType": "email", "identifier": EMAIL}],
}


@pytest.fixture
def plugin() -> BSICompliancePlugin:
    return BSICompliancePlugin()


class TestSpdx3Refs:
    """The normaliser the three readers share."""

    def test_a_list_passes_through(self):
        assert spdx3_refs(["urn:a", "urn:b"]) == ["urn:a", "urn:b"]

    def test_a_bare_string_is_a_singleton(self):
        """Not eleven refs of one character each."""
        assert spdx3_refs("urn:acme") == ["urn:acme"]

    def test_an_inline_object_is_a_singleton(self):
        """Agent_derived allows the object inline, without a graph entry."""
        agent = {"type": "Organization", "name": "Acme"}
        assert spdx3_refs(agent) == [agent]

    def test_a_missing_field_resolves_nobody(self):
        assert spdx3_refs(None) == []

    @pytest.mark.parametrize("hostile", [0, 1.5, True])
    def test_a_hostile_scalar_resolves_nobody(self, hostile):
        assert spdx3_refs(hostile) == []


class TestSbomCreator:
    def test_a_list_createdby_reads_the_creator(self, plugin):
        creator = plugin._get_spdx3_sbom_creator({"createdBy": ["urn:acme"]}, {"urn:acme": _ACME})

        assert creator == EMAIL

    def test_a_compact_createdby_reads_the_same_creator(self, plugin):
        """One element, written the way JSON-LD compacts it."""
        creator = plugin._get_spdx3_sbom_creator({"createdBy": "urn:acme"}, {"urn:acme": _ACME})

        assert creator == EMAIL

    def test_an_inline_agent_reads_the_creator(self, plugin):
        creator = plugin._get_spdx3_sbom_creator({"createdBy": _ACME}, {})

        assert creator == EMAIL

    def test_a_url_creator_is_accepted(self, plugin):
        org = {
            "type": "Organization",
            "name": "Acme",
            "externalIdentifier": [{"externalIdentifierType": "urlScheme", "identifier": URL}],
        }

        assert plugin._get_spdx3_sbom_creator({"createdBy": org}, {}) == URL

    def test_no_createdby_still_reads_nobody(self, plugin):
        assert plugin._get_spdx3_sbom_creator({}, {}) is None

    def test_a_creator_without_contact_details_still_reads_nobody(self, plugin):
        """The check is for an email or URL, not for a name."""
        assert plugin._get_spdx3_sbom_creator({"createdBy": {"type": "Organization", "name": "Acme"}}, {}) is None


class TestComponentCreator:
    def test_a_list_originatedby_reads_the_creator(self, plugin):
        creator = plugin._get_spdx3_component_creator({"originatedBy": ["urn:acme"]}, {"urn:acme": _ACME})

        assert creator == EMAIL

    def test_a_compact_originatedby_reads_the_same_creator(self, plugin):
        creator = plugin._get_spdx3_component_creator({"originatedBy": "urn:acme"}, {"urn:acme": _ACME})

        assert creator == EMAIL

    def test_an_inline_agent_reads_the_creator(self, plugin):
        assert plugin._get_spdx3_component_creator({"originatedBy": _ACME}, {}) == EMAIL

    def test_no_originatedby_still_reads_nobody(self, plugin):
        assert plugin._get_spdx3_component_creator({}, {}) is None


class TestSupplierOnAPackage:
    """``get_spdx3_package_fields`` feeds NTIA, CISA and FDA supplier checks."""

    def test_a_list_originatedby_finds_the_supplier(self):
        fields = get_spdx3_package_fields({"name": "acl", "originatedBy": ["urn:acme"]})

        assert has_spdx3_supplier(fields["supplier_refs"], {"urn:acme": _ACME})

    def test_a_compact_originatedby_finds_the_same_supplier(self):
        fields = get_spdx3_package_fields({"name": "acl", "originatedBy": "urn:acme"})

        assert has_spdx3_supplier(fields["supplier_refs"], {"urn:acme": _ACME})

    def test_an_inline_agent_finds_the_supplier(self):
        """Agent_derived allows the object inline, with no graph entry to
        resolve. Today it falls out of the list check and scores as no
        supplier, which costs three NTIA findings."""
        fields = get_spdx3_package_fields({"name": "acl", "originatedBy": _ACME})

        assert has_spdx3_supplier(fields["supplier_refs"], {})

    def test_a_compact_suppliedby_is_the_fallback(self):
        fields = get_spdx3_package_fields({"name": "acl", "suppliedBy": "urn:acme"})

        assert has_spdx3_supplier(fields["supplier_refs"], {"urn:acme": _ACME})

    def test_no_supplier_field_finds_nobody(self):
        fields = get_spdx3_package_fields({"name": "acl"})

        assert not has_spdx3_supplier(fields["supplier_refs"], {"urn:acme": _ACME})


class TestToolsOnCreationInfo:
    """``createdUsing`` is a set too, and carries the sbomify-action check."""

    _TOOL = {"type": "Tool", "spdxId": "urn:tool", "name": "sbomify-action-1.2.3"}

    def test_a_list_createdusing_reads_the_tool(self):
        fields = get_spdx3_creation_info_fields({"createdUsing": ["urn:tool"]}, {}, {"urn:tool": self._TOOL})

        assert fields["tool_entries"] == ["sbomify-action-1.2.3"]

    def test_a_compact_createdusing_reads_the_same_tool(self):
        fields = get_spdx3_creation_info_fields({"createdUsing": "urn:tool"}, {}, {"urn:tool": self._TOOL})

        assert fields["tool_entries"] == ["sbomify-action-1.2.3"]

    def test_an_inline_tool_reads_its_name(self):
        fields = get_spdx3_creation_info_fields({"createdUsing": self._TOOL}, {}, {})

        assert fields["tool_entries"] == ["sbomify-action-1.2.3"]

    def test_an_unresolvable_ref_is_kept_as_itself(self):
        """Better a URN in the tool list than a document that names no tool."""
        fields = get_spdx3_creation_info_fields({"createdUsing": "urn:unknown"}, {}, {})

        assert fields["tool_entries"] == ["urn:unknown"]


class TestTheCisa2026Plugin:
    """The current standard, and the last reader still carrying its own copies
    of this normalisation: one each for createdBy, createdUsing and the
    originatedBy/suppliedBy pair. All three read a bare string and none read a
    bare object, so an inline Agent scored as nobody.
    """

    @pytest.fixture
    def plugin(self):
        from sbomify.apps.plugins.builtins.cisa_2026 import CISAMinimumElementsPlugin

        return CISAMinimumElementsPlugin()

    _PERSON = {"type": "Person", "spdxId": "urn:someone", "name": "A Person"}
    _TOOL = {"type": "Tool", "spdxId": "urn:tool", "name": "syft 1.2.3"}

    @pytest.mark.parametrize(
        "created_by",
        [
            pytest.param(["urn:someone"], id="list"),
            pytest.param("urn:someone", id="compact string"),
            pytest.param(_PERSON, id="inline object"),
            pytest.param([_PERSON], id="list of one inline object"),
        ],
    )
    def test_every_shape_names_the_author(self, plugin, created_by):
        assert plugin._spdx3_has_author({"createdBy": created_by}, {"urn:someone": self._PERSON}) is True

    def test_a_software_agent_is_the_tool_not_the_author(self, plugin):
        """Unchanged by the shared helper: the standard separates them."""
        agent = {"type": "SoftwareAgent", "spdxId": "urn:bot", "name": "a bot"}

        assert plugin._spdx3_has_author({"createdBy": agent}, {}) is False

    @pytest.mark.parametrize(
        "created_using",
        [
            pytest.param(["urn:tool"], id="list"),
            pytest.param("urn:tool", id="compact string"),
            pytest.param(_TOOL, id="inline object"),
        ],
    )
    def test_every_shape_finds_the_tool(self, plugin, created_using):
        found = plugin._spdx3_tools({"createdUsing": created_using}, {"urn:tool": self._TOOL}, {})

        assert [t.get("name") for t in found] == ["syft 1.2.3"]

    @pytest.mark.parametrize("key", ["originatedBy", "suppliedBy"])
    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(["urn:someone"], id="list"),
            pytest.param("urn:someone", id="compact string"),
            pytest.param(_PERSON, id="inline object"),
        ],
    )
    def test_every_shape_names_the_producer(self, plugin, key, value):
        names = plugin._spdx3_producer_names({key: value}, {"urn:someone": self._PERSON})

        assert names == ["A Person"]

    def test_noassertion_still_counts_as_naming_nobody_explicitly(self, plugin):
        assert plugin._spdx3_producer_names({"originatedBy": "NOASSERTION"}, {}) == ["NOASSERTION"]

    def test_a_package_naming_nobody_names_nobody(self, plugin):
        assert plugin._spdx3_producer_names({}, {}) == []
