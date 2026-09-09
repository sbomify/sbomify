"""An external-reference type written as an IRI is the same type as the bare term.

SPDX 2.x permits `referenceType` as the bare term or as the full IRI it
abbreviates. Every compliance plugin compared against bare terms only, so a
package identified solely by an IRI-form cpe23Type scored as having no
identifier at all.

Yocto writes the IRI and nothing else: all 108 external references across the
176 documents of the Yocto Project's 5.0.5 release SBOM are
`http://spdx.org/rdf/references/cpe23Type`, so an entire Yocto build scored
zero identifiers.
"""

from __future__ import annotations

from typing import Any

import pytest

from sbomify.apps.plugins.builtins.bsi import BSICompliancePlugin
from sbomify.apps.plugins.builtins.cisa import CISAMinimumElementsPlugin
from sbomify.apps.plugins.builtins.fda_medical_device_cybersecurity import FDAMedicalDevicePlugin
from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin

BARE = "cpe23Type"
IRI = "http://spdx.org/rdf/references/cpe23Type"
CPE = "cpe:2.3:*:openssl:openssl:3.2.3:*:*:*:*:*:*:*"

#: Each plugin with the exact finding id its identifier check reports under, and
#: the extra arguments its _validate_spdx takes. BSI wants the version because
#: TR-03183-2 grades 2.x and 3.x differently; the rest take the document alone.
PLUGINS = [
    pytest.param(CISAMinimumElementsPlugin, "cisa-2025:software-identifiers", (), id="cisa"),
    pytest.param(NTIAMinimumElementsPlugin, "ntia-2021:unique-identifiers", (), id="ntia"),
    pytest.param(BSICompliancePlugin, "bsi-tr03183:unique-identifiers", ("2.2",), id="bsi"),
    pytest.param(FDAMedicalDevicePlugin, "fda-2025:ntia:unique-identifiers", (), id="fda"),
]


def _document(reference_type: str) -> dict[str, Any]:
    """One SPDX 2.2 package whose only identifier is a CPE, as Yocto emits it."""
    return {
        "spdxVersion": "SPDX-2.2",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "recipe-openssl",
        "documentNamespace": "http://spdx.org/spdxdocs/recipe-openssl-0f2c1f0e",
        "creationInfo": {
            "created": "2026-01-01T00:00:00Z",
            "creators": ["Tool: OpenEmbedded Core create-spdx.bbclass", "Organization: OpenEmbedded"],
        },
        "packages": [
            {
                "SPDXID": "SPDXRef-Recipe-openssl",
                "name": "openssl",
                "versionInfo": "3.2.3",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "supplier": "Organization: OpenEmbedded ()",
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "OpenSSL",
                "copyrightText": "NOASSERTION",
                "checksums": [{"algorithm": "SHA256", "checksumValue": "a" * 64}],
                "externalRefs": [
                    {
                        "referenceCategory": "SECURITY",
                        "referenceType": reference_type,
                        "referenceLocator": CPE,
                    }
                ],
            }
        ],
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-Recipe-openssl",
            }
        ],
    }


def _identifier_finding(plugin_cls: type, finding_id: str, extra_args: tuple, reference_type: str):
    findings = plugin_cls()._validate_spdx(_document(reference_type), *extra_args)
    matches = [f for f in findings if getattr(f, "id", None) == finding_id]
    assert matches, (
        f"{plugin_cls.__name__} reported no finding {finding_id!r}; "
        f"it reported {[getattr(f, 'id', None) for f in findings]}"
    )
    return matches[0]


@pytest.mark.parametrize(("plugin_cls", "finding_id", "extra_args"), PLUGINS)
class TestTheIriSpellingIsReadAsAnIdentifier:
    def test_the_iri_form_scores_as_an_identifier(self, plugin_cls: type, finding_id: str, extra_args: tuple) -> None:
        finding = _identifier_finding(plugin_cls, finding_id, extra_args, IRI)

        assert finding.status != "fail", (
            f"{plugin_cls.__name__} scored a package carrying {CPE} as missing an identifier"
        )

    def test_the_bare_form_still_scores_as_one(self, plugin_cls: type, finding_id: str, extra_args: tuple) -> None:
        """The guard against a fix that stops reading the spelling everyone else writes."""
        finding = _identifier_finding(plugin_cls, finding_id, extra_args, BARE)

        assert finding.status != "fail"
