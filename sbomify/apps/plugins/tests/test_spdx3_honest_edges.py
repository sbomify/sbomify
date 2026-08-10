"""The messages a user actually sees at the SPDX 3 edges, made actionable.

- BSI's floor failure told a 3.0 sender "does not meet minimum requirement
  of 3.0.1" and nothing else — one patch digit short, with no hint that
  cdxgen or a Yocto upgrade emits 3.0.1.
- OSV's skip finding said scanning "requires SPDX 2.x or CycloneDX" without
  naming the one-command conversion that gets a user there.

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
    def test_names_the_conversion_workaround(self) -> None:
        result = OSVPlugin()._create_unsupported_format_result()

        description = result.findings[0].description
        assert "syft convert" in description


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
