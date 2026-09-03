"""The messages a user actually sees at the SPDX 3 edges, made actionable.

- BSI's floor failure told a 3.0 sender "does not meet minimum requirement
  of 3.0.1" and nothing else — one patch digit short, with no hint that
  cdxgen or a Yocto upgrade emits 3.0.1.
- OSV's skip finding said scanning "requires SPDX 2.x or CycloneDX" without
  saying why nothing was scanned. It now names the missing piece: the server
  derives a scannable copy itself, so this path means no converter is
  available on the deployment.

And the single detector: ``is_spdx3`` now also recognises a bare ``@graph``
document and any 3.x context, so every caller shares one answer.
"""

from __future__ import annotations

from sbomify.apps.plugins.builtins._spdx3_helpers import is_spdx3
from sbomify.apps.plugins.builtins.bsi import BSICompliancePlugin
from sbomify.apps.plugins.builtins.osv import OSVPlugin


class TestBsiFloorMessage:
    def test_spdx_3_0_failure_names_the_source_and_a_way_out(self) -> None:
        finding = BSICompliancePlugin()._check_format_version("spdx", "3.0")

        assert finding.status == "fail"
        remediation = finding.remediation or ""
        assert "TR-03183-2" in remediation
        assert "3.0.1" in remediation
        assert "cdxgen" in remediation
        assert "Yocto" in remediation

    def test_spdx_3_0_1_still_passes(self) -> None:
        assert BSICompliancePlugin()._check_format_version("spdx", "3.0.1").status == "pass"

    def test_spdx_2_3_keeps_its_existing_message(self) -> None:
        finding = BSICompliancePlugin()._check_format_version("spdx", "2.3")

        assert finding.status == "fail"
        assert "regenerate" in (finding.remediation or "").lower()


class TestOsvSkipMessage:
    def test_says_the_converter_is_missing_rather_than_asking_for_a_manual_one(self) -> None:
        """This path now means the deployment has no converter, not that the reader needs one.

        The message used to name ``syft convert`` as the workaround. The
        server derives that copy itself now, so reaching this result says no
        converter is available here, and telling a reader to convert the
        document by hand would point them at the wrong problem.
        """
        result = OSVPlugin()._create_unsupported_format_result()

        description = result.findings[0].description
        assert "no working converter is available" in description
        assert "syft convert" not in description


class TestOneDetector:
    def test_bare_graph_document_is_spdx3(self) -> None:
        """The release builders' shape test, folded into the shared detector."""
        assert is_spdx3({"@graph": [{"type": "software_Package", "name": "p"}]}) is True

    def test_any_3x_context_is_spdx3(self) -> None:
        assert is_spdx3({"@context": "https://spdx.org/rdf/3.1.0/spdx-context.jsonld"}) is True

    def test_cyclonedx_is_not(self) -> None:
        assert is_spdx3({"bomFormat": "CycloneDX", "specVersion": "1.6"}) is False

    def test_spdx2_is_not(self) -> None:
        assert is_spdx3({"spdxVersion": "SPDX-2.3", "packages": []}) is False

    def test_non_list_graph_is_not_spdx3(self) -> None:
        """An arbitrary JSON object with a scalar @graph key must not be
        classified as SPDX 3 — callers iterate the graph."""
        assert is_spdx3({"@graph": "not-a-list"}) is False
        assert is_spdx3({"@graph": 42}) is False


class TestSbomTypeGenerationContext:
    """The CISA 2026 mapping puts SPDX 3's Generation Context at
    Software/Sbom.sbomType — the first-class field. The check read only
    comments and annotations, so Yocto's sbomType: ["build"] with no
    explanatory comment failed generation context despite declaring it
    per spec."""

    def _has_context(self, *graph: object) -> bool:
        from sbomify.apps.plugins.builtins.cisa import CISAMinimumElementsPlugin

        doc = {"@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld", "@graph": list(graph)}
        return CISAMinimumElementsPlugin()._spdx3_has_generation_context(doc)

    def test_sbom_type_declares_the_context(self) -> None:
        assert (
            self._has_context(
                {"type": "software_Sbom", "spdxId": "urn:x:sbom", "software_sbomType": ["build"]},
            )
            is True
        )

    def test_empty_sbom_type_does_not(self) -> None:
        assert self._has_context({"type": "software_Sbom", "spdxId": "urn:x:sbom", "software_sbomType": []}) is False
        assert self._has_context({"type": "software_Sbom", "spdxId": "urn:x:sbom"}) is False

    def test_no_sbom_element_keeps_failing(self) -> None:
        assert self._has_context({"type": "software_Package", "spdxId": "urn:x:p", "name": "p"}) is False
