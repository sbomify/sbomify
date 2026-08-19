"""Three single-field SPDX 3 reads, each pointed at a property the spec has.

- FDA end-of-support read ``software_validUntilDate``, which exists in no
  SPDX 3.0.1 properties block. The spec property is ``validUntilTime`` on
  Artifact. The check could never pass via the package field.
- BSI's source-code-URI check looked for an ``externalIdentifier`` of type
  ``vcs`` or ``url`` — neither value exists in the ExternalIdentifierType
  vocabulary. ``vcs`` lives in ExternalRefType, so it belongs on
  ``externalRef``.
- sbomify-action detection read root ``creationInfo.creators[]``, which
  SPDX 3 does not have — tools live in ``createdUsing`` pointing at Tool
  elements — so SPDX 3 users who already run the action still saw the
  "use sbomify-action" CTA.

Legacy spellings stay readable in all three: stored artifacts carry them.
"""

from __future__ import annotations

from typing import Any

from sbomify.apps.plugins.builtins.bsi import BSICompliancePlugin
from sbomify.apps.plugins.builtins.fda_medical_device_cybersecurity import FDAMedicalDevicePlugin
from sbomify.apps.sboms.utils import _spdx3_metadata_has_sbomify_action

CONTEXT = "https://spdx.org/rdf/3.0.1/spdx-context.jsonld"

END_OF_SUPPORT = "fda-2025:cle:end-of-support"


def _fda_doc(package_extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "@context": CONTEXT,
        "@graph": [
            {"type": "CreationInfo", "spdxId": "urn:ci", "created": "2026-01-01T00:00:00Z"},
            {"type": "software_Package", "spdxId": "urn:p1", "name": "dev-firmware", **package_extra},
        ],
    }


def _end_of_support_finding(doc: dict[str, Any]) -> Any:
    findings = FDAMedicalDevicePlugin()._validate_spdx3(doc)
    return next(f for f in findings if f.id == END_OF_SUPPORT)


class TestFdaEndOfSupport:
    def test_valid_until_time_passes(self) -> None:
        finding = _end_of_support_finding(_fda_doc({"validUntilTime": "2030-01-01T00:00:00Z"}))

        assert finding.status == "pass"

    def test_legacy_field_still_passes(self) -> None:
        finding = _end_of_support_finding(_fda_doc({"software_validUntilDate": "2030-01-01"}))

        assert finding.status == "pass"

    def test_neither_still_fails(self) -> None:
        finding = _end_of_support_finding(_fda_doc({}))

        assert finding.status == "fail"


class TestBsiSourceCodeUri:
    def _has_uri(self, package_extra: dict[str, Any]) -> bool:
        package = {"type": "software_Package", "spdxId": "urn:p", "name": "p", **package_extra}
        return BSICompliancePlugin()._spdx3_has_source_code_uri(package)

    def test_external_ref_vcs_passes(self) -> None:
        assert (
            self._has_uri({"externalRef": [{"externalRefType": "vcs", "locator": ["https://github.com/acme/p"]}]})
            is True
        )

    def test_external_ref_source_artifact_passes(self) -> None:
        assert (
            self._has_uri(
                {"externalRef": [{"externalRefType": "sourceArtifact", "locator": ["https://acme.test/src.tgz"]}]}
            )
            is True
        )

    def test_locator_as_bare_string(self) -> None:
        """JSON-LD compact form: a one-element set may serialise unwrapped."""
        assert (
            self._has_uri({"externalRef": [{"externalRefType": "vcs", "locator": "https://github.com/acme/p"}]}) is True
        )

    def test_source_info_fallback_unchanged(self) -> None:
        assert self._has_uri({"software_sourceInfo": "built from https://github.com/acme/p"}) is True

    def test_legacy_invalid_identifier_shape_still_accepted(self) -> None:
        """Documents stored before the fix carry the not-in-vocabulary shape."""
        assert (
            self._has_uri(
                {"externalIdentifiers": [{"externalIdentifierType": "vcs", "identifier": "https://github.com/acme/p"}]}
            )
            is True
        )

    def test_nothing_still_fails(self) -> None:
        assert self._has_uri({}) is False
        assert self._has_uri({"externalRef": [{"externalRefType": "binaryArtifact", "locator": ["x"]}]}) is False


class TestSpdx3ActionDetection:
    def _doc(self, tool_name: str) -> dict[str, Any]:
        return {
            "@context": CONTEXT,
            "@graph": [
                {"type": "Tool", "spdxId": "urn:tool", "name": tool_name},
                {"type": "CreationInfo", "spdxId": "urn:ci", "createdUsing": ["urn:tool"]},
            ],
        }

    def test_tool_element_named_sbomify_action(self) -> None:
        assert _spdx3_metadata_has_sbomify_action(self._doc("sbomify-action")) is True

    def test_versioned_tool_name(self) -> None:
        """augmentation.py writes f"{name}-{version}"."""
        assert _spdx3_metadata_has_sbomify_action(self._doc("sbomify-action-1.2.3")) is True

    def test_other_tool_keeps_the_cta(self) -> None:
        assert _spdx3_metadata_has_sbomify_action(self._doc("syft-1.46.0")) is False

    def test_lookalike_wrapper_is_not_the_action(self) -> None:
        """Same rule as the SPDX 2 creator parser: only a trailing version
        segment is stripped, so a different generator wrapping the name does
        not hide the CTA."""
        assert _spdx3_metadata_has_sbomify_action(self._doc("sbomify-action-v2-wrapper")) is False

    def test_malformed_document_is_false(self) -> None:
        assert _spdx3_metadata_has_sbomify_action({"@graph": "not a list"}) is False
        assert _spdx3_metadata_has_sbomify_action(None) is False
