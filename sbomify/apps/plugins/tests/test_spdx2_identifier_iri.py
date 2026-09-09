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

#: Each plugin with the finding id its identifier check reports under.
PLUGINS = [
    pytest.param(CISAMinimumElementsPlugin, "software-identifiers", id="cisa"),
    pytest.param(NTIAMinimumElementsPlugin, "unique-identifiers", id="ntia"),
    pytest.param(BSICompliancePlugin, "identifier", id="bsi"),
    pytest.param(FDAMedicalDevicePlugin, "identifier", id="fda"),
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


def _identifier_finding(plugin_cls: type, finding_id_part: str, reference_type: str):
    import inspect

    plugin = plugin_cls()
    document = _document(reference_type)
    # BSI takes the version too, since TR-03183-2 grades 2.x and 3.x differently.
    if "format_version" in inspect.signature(plugin._validate_spdx).parameters:
        findings = plugin._validate_spdx(document, "2.2")
    else:
        findings = plugin._validate_spdx(document)
    matches = [f for f in findings if finding_id_part in str(getattr(f, "id", "")).lower()]
    assert matches, f"{plugin_cls.__name__} reported no identifier check at all"
    return matches[0]


@pytest.mark.parametrize(("plugin_cls", "finding_id_part"), PLUGINS)
class TestTheIriSpellingIsReadAsAnIdentifier:
    def test_the_iri_form_scores_as_an_identifier(self, plugin_cls: type, finding_id_part: str) -> None:
        finding = _identifier_finding(plugin_cls, finding_id_part, IRI)

        assert finding.status != "fail", (
            f"{plugin_cls.__name__} scored a package carrying {CPE} as missing an identifier"
        )

    def test_the_bare_form_still_scores_as_one(self, plugin_cls: type, finding_id_part: str) -> None:
        """The guard against a fix that stops reading the spelling everyone else writes."""
        finding = _identifier_finding(plugin_cls, finding_id_part, BARE)

        assert finding.status != "fail"
