"""SPDX 3 licence relationships resolve to expressions, not booleans.

The plugins used to check only that a ``hasConcludedLicense`` /
``hasDeclaredLicense`` relationship *existed*; a relationship pointing at
nothing resolvable scored the same as a real licence. These pin the
resolver across the element kinds the spec allows and the failure the
plugins must now report for a dangling target.
"""

from __future__ import annotations

from typing import Any

from sbomify.apps.plugins.builtins._spdx3_helpers import (
    extract_spdx3_licenses,
    get_spdx3_package_license,
    resolve_spdx3_license_expression,
)
from sbomify.apps.plugins.tests import spdx3_corpus


def _graph(*elements: dict[str, Any]) -> dict[str, Any]:
    return {"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": list(elements)}


EXPRESSION = {
    "type": "simplelicensing_LicenseExpression",
    "spdxId": "urn:acme:lic1",
    "simplelicensing_licenseExpression": "Apache-2.0 OR MIT",
}
LISTED = {
    "type": "expandedlicensing_ListedLicense",
    "spdxId": "https://spdx.org/licenses/MIT",
    "name": "MIT",
}
NOASSERTION = {
    "type": "expandedlicensing_NoAssertionLicense",
    "spdxId": "urn:acme:noassert",
}


class TestResolver:
    def test_license_expression_resolves_to_its_expression(self):
        licenses = extract_spdx3_licenses(_graph(EXPRESSION))
        assert resolve_spdx3_license_expression("urn:acme:lic1", licenses) == "Apache-2.0 OR MIT"

    def test_listed_license_resolves_to_its_name(self):
        licenses = extract_spdx3_licenses(_graph(LISTED))
        assert resolve_spdx3_license_expression("https://spdx.org/licenses/MIT", licenses) == "MIT"

    def test_spdx_listed_url_without_an_element_resolves_to_the_id_tail(self):
        assert resolve_spdx3_license_expression("https://spdx.org/licenses/BSD-3-Clause", {}) == "BSD-3-Clause"

    def test_noassertion_resolves_to_nothing(self):
        licenses = extract_spdx3_licenses(_graph(NOASSERTION))
        assert resolve_spdx3_license_expression("urn:acme:noassert", licenses) is None

    def test_dangling_reference_resolves_to_nothing(self):
        assert resolve_spdx3_license_expression("urn:acme:missing", {}) is None

    def test_inline_target_resolves_without_a_graph_element(self):
        assert resolve_spdx3_license_expression(dict(EXPRESSION), {}) == "Apache-2.0 OR MIT"


class TestPackageLicense:
    def test_declared_license_resolves_through_the_relationship(self):
        package = {"type": "software_Package", "spdxId": "urn:acme:pkg1", "name": "my-app"}
        relationships = [
            {
                "type": "Relationship",
                "relationshipType": "hasDeclaredLicense",
                "from": "urn:acme:pkg1",
                "to": ["urn:acme:lic1"],
            }
        ]
        licenses = extract_spdx3_licenses(_graph(EXPRESSION))
        assert get_spdx3_package_license(package, relationships, licenses, "hasDeclaredLicense") == "Apache-2.0 OR MIT"

    def test_relationship_to_nothing_resolvable_yields_none(self):
        package = {"type": "software_Package", "spdxId": "urn:acme:pkg1", "name": "my-app"}
        relationships = [
            {
                "type": "Relationship",
                "relationshipType": "hasConcludedLicense",
                "from": "urn:acme:pkg1",
                "to": ["urn:acme:missing"],
            }
        ]
        assert get_spdx3_package_license(package, relationships, {}, "hasConcludedLicense") is None


class TestPluginsFailOnDanglingLicence:
    def _dangling(self) -> dict[str, Any]:
        """The conformant corpus doc with its licence element removed — the
        relationships still point at urn:acme:lic1, now dangling."""
        doc = spdx3_corpus.minimal_conformant()
        doc["@graph"] = [element for element in doc["@graph"] if "License" not in str(element.get("type", ""))]
        return doc

    def _licence_statuses(self, findings: list[Any]) -> list[str]:
        return [finding.status for finding in findings if "licen" in finding.id.lower()]

    def test_bsi_licence_check_fails(self):
        from sbomify.apps.plugins.builtins.bsi import BSICompliancePlugin

        findings = BSICompliancePlugin()._validate_spdx3(self._dangling())
        assert "fail" in self._licence_statuses(findings)

    def test_cisa_licence_check_fails(self):
        from sbomify.apps.plugins.builtins.cisa import CISAMinimumElementsPlugin

        findings = CISAMinimumElementsPlugin()._validate_spdx3(self._dangling())
        assert "fail" in self._licence_statuses(findings)

    def test_conformant_corpus_still_passes_licence_checks(self):
        from sbomify.apps.plugins.builtins.bsi import BSICompliancePlugin
        from sbomify.apps.plugins.builtins.cisa import CISAMinimumElementsPlugin

        doc = spdx3_corpus.minimal_conformant()
        for plugin in (BSICompliancePlugin(), CISAMinimumElementsPlugin()):
            statuses = self._licence_statuses(plugin._validate_spdx3(doc))
            assert "fail" not in statuses
