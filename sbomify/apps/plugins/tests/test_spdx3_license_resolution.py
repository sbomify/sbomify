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


class TestCompoundShapes:
    """The ExpandedLicensing sets and operators compose into expressions.

    A package whose hasDeclaredLicense points at a ConjunctiveLicenseSet used
    to resolve to nothing and fail the check as unresolvable, though the
    document declared its licence exactly as the 3.0.1 model prescribes.
    """

    APACHE = {"type": "expandedlicensing_ListedLicense", "spdxId": "https://spdx.org/licenses/Apache-2.0", "name": "Apache-2.0"}
    GPL = {"type": "expandedlicensing_ListedLicense", "spdxId": "https://spdx.org/licenses/GPL-2.0-only", "name": "GPL-2.0-only"}
    EXCEPTION = {
        "type": "expandedlicensing_ListedLicenseException",
        "spdxId": "urn:acme:classpath",
        "name": "Classpath-exception-2.0",
    }

    def test_conjunctive_set_joins_with_and(self):
        conj = {
            "type": "expandedlicensing_ConjunctiveLicenseSet",
            "spdxId": "urn:acme:conj",
            "expandedlicensing_member": [LISTED["spdxId"], self.APACHE["spdxId"]],
        }
        licenses = extract_spdx3_licenses(_graph(conj, LISTED, self.APACHE))
        assert resolve_spdx3_license_expression("urn:acme:conj", licenses) == "MIT AND Apache-2.0"

    def test_nested_set_is_parenthesized(self):
        disj = {
            "type": "expandedlicensing_DisjunctiveLicenseSet",
            "spdxId": "urn:acme:disj",
            "expandedlicensing_member": [LISTED["spdxId"], self.APACHE["spdxId"]],
        }
        conj = {
            "type": "expandedlicensing_ConjunctiveLicenseSet",
            "spdxId": "urn:acme:conj",
            "expandedlicensing_member": ["urn:acme:disj", self.GPL["spdxId"]],
        }
        licenses = extract_spdx3_licenses(_graph(conj, disj, LISTED, self.APACHE, self.GPL))
        assert resolve_spdx3_license_expression("urn:acme:conj", licenses) == "(MIT OR Apache-2.0) AND GPL-2.0-only"

    def test_or_later_appends_plus(self):
        later = {
            "type": "expandedlicensing_OrLaterOperator",
            "spdxId": "urn:acme:later",
            "expandedlicensing_subjectLicense": self.GPL["spdxId"],
        }
        licenses = extract_spdx3_licenses(_graph(later, self.GPL))
        assert resolve_spdx3_license_expression("urn:acme:later", licenses) == "GPL-2.0-only+"

    def test_with_addition_names_the_exception(self):
        with_op = {
            "type": "expandedlicensing_WithAdditionOperator",
            "spdxId": "urn:acme:with",
            "expandedlicensing_subjectLicense": self.GPL["spdxId"],
            "expandedlicensing_subjectAddition": "urn:acme:classpath",
        }
        licenses = extract_spdx3_licenses(_graph(with_op, self.GPL, self.EXCEPTION))
        assert (
            resolve_spdx3_license_expression("urn:acme:with", licenses)
            == "GPL-2.0-only WITH Classpath-exception-2.0"
        )

    def test_a_set_with_an_unresolvable_member_resolves_to_nothing(self):
        conj = {
            "type": "expandedlicensing_ConjunctiveLicenseSet",
            "spdxId": "urn:acme:conj",
            "expandedlicensing_member": [LISTED["spdxId"], "urn:acme:missing"],
        }
        licenses = extract_spdx3_licenses(_graph(conj, LISTED))
        assert resolve_spdx3_license_expression("urn:acme:conj", licenses) is None

    def test_a_spoofed_licenses_url_does_not_resolve(self):
        """spdx.org/licenses/ buried in a hostile URL must not score."""
        assert resolve_spdx3_license_expression("https://evil.example/spdx.org/licenses/MIT", {}) is None
        assert resolve_spdx3_license_expression("https://spdx.org.evil.example/licenses/MIT", {}) is None
        assert resolve_spdx3_license_expression("https://spdx.org/licenses/", {}) is None

    def test_a_named_simple_licensing_text_resolves_to_its_name(self):
        """Free-text licences with a name score by that name; a nameless one
        has no expression to score and stays None."""
        named = {
            "type": "simplelicensing_SimpleLicensingText",
            "spdxId": "urn:acme:freetext",
            "name": "Acme Proprietary 1.0",
            "simplelicensing_licenseText": "You may...",
        }
        licenses = extract_spdx3_licenses(_graph(named))
        assert resolve_spdx3_license_expression("urn:acme:freetext", licenses) == "Acme Proprietary 1.0"

        nameless = dict(named)
        del nameless["name"]
        nameless["spdxId"] = "urn:acme:nameless"
        licenses = extract_spdx3_licenses(_graph(nameless))
        # Still a licence: it resolves to its id, the one string that
        # identifies it without dumping the text into a report.
        assert resolve_spdx3_license_expression("urn:acme:nameless", licenses) == "urn:acme:nameless"

    def test_compact_iri_types_are_collected_and_resolved(self):
        """JSON-LD compact IRIs spell the type with a colon; the tail reader
        must see through that as it does the slash and underscore forms."""
        expr = {
            "type": "simplelicensing:LicenseExpression",
            "spdxId": "urn:acme:compact",
            "simplelicensing_licenseExpression": "BSD-2-Clause",
        }
        noassert = {"type": "expandedlicensing:NoAssertionLicense", "spdxId": "urn:acme:na"}
        licenses = extract_spdx3_licenses(_graph(expr, noassert))
        assert resolve_spdx3_license_expression("urn:acme:compact", licenses) == "BSD-2-Clause"
        assert resolve_spdx3_license_expression("urn:acme:na", licenses) is None

    def test_a_self_citing_set_terminates(self):
        conj = {
            "type": "expandedlicensing_ConjunctiveLicenseSet",
            "spdxId": "urn:acme:conj",
            "expandedlicensing_member": ["urn:acme:conj", LISTED["spdxId"]],
        }
        licenses = extract_spdx3_licenses(_graph(conj, LISTED))
        assert resolve_spdx3_license_expression("urn:acme:conj", licenses) is None


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
