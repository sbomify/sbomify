"""Tests for the FDA Medical Device Cybersecurity compliance plugin.

Tests validation of SBOMs against FDA guidance 'Cybersecurity in Medical Devices:
Quality System Considerations and Content of Premarket Submissions' (June 2025).

This plugin validates:
- 7 NTIA minimum elements (baseline)
- 2 FDA-specific CLE elements (support status, end-of-support date)
"""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from sbomify.apps.plugins.builtins.fda_medical_device_cybersecurity import (
    CLE_SUPPORT_STATUS_VALUES,
    FDAMedicalDevicePlugin,
)
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
from sbomify.apps.plugins.sdk.results import AssessmentResult


class TestFDAPluginMetadata:
    """Tests for plugin metadata."""

    def test_plugin_metadata(self) -> None:
        """Test that plugin returns correct metadata."""
        plugin = FDAMedicalDevicePlugin()
        metadata = plugin.get_metadata()

        assert metadata.name == "fda-medical-device-2025"
        assert metadata.version == "1.0.0"
        assert metadata.category == AssessmentCategory.COMPLIANCE

    def test_plugin_standard_info(self) -> None:
        """Test that plugin has correct standard information."""
        plugin = FDAMedicalDevicePlugin()

        assert plugin.STANDARD_NAME == "FDA Cybersecurity in Medical Devices"
        assert plugin.STANDARD_VERSION == "2025-06"
        assert plugin.STANDARD_URL == "https://www.fda.gov/media/119933/download"

    def test_finding_ids_use_fda_prefix(self) -> None:
        """Test that NTIA finding IDs are prefixed with fda-2025:ntia."""
        plugin = FDAMedicalDevicePlugin()

        for key, finding_id in plugin.NTIA_FINDING_IDS.items():
            assert finding_id.startswith("fda-2025:ntia:"), (
                f"NTIA finding ID {finding_id} should start with 'fda-2025:ntia:'"
            )

    def test_fda_finding_ids_use_cle_prefix(self) -> None:
        """Test that FDA-specific finding IDs are prefixed with fda-2025:cle."""
        plugin = FDAMedicalDevicePlugin()

        for key, finding_id in plugin.FDA_FINDING_IDS.items():
            assert finding_id.startswith("fda-2025:cle:"), (
                f"FDA finding ID {finding_id} should start with 'fda-2025:cle:'"
            )

    def test_cle_support_status_values(self) -> None:
        """Test that valid CLE support status values are defined."""
        expected_values = {"active", "deprecated", "eol", "abandoned", "unknown"}
        assert CLE_SUPPORT_STATUS_VALUES == expected_values


class TestCycloneDXValidation:
    """Tests for CycloneDX SBOM validation."""

    def test_compliant_cyclonedx_sbom_with_cle(self) -> None:
        """Test validation of a fully compliant CycloneDX SBOM with CLE data."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    "properties": [
                        {"name": "cdx:lifecycle:milestone:endOfSupport", "value": "2027-12-31"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 0
        assert result.summary.pass_count == 9  # 7 NTIA + 2 CLE elements
        assert result.summary.total_findings == 9

    def test_cyclonedx_endOfSupport_satisfies_both_cle_checks(self) -> None:
        """A single cdx:lifecycle:milestone:endOfSupport on a component
        should satisfy both the End-of-Support finding (specific date) and
        the Support Status finding (status derivable from the milestone).
        """
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    "properties": [
                        {"name": "cdx:lifecycle:milestone:endOfSupport", "value": "2027-12-31"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        eos_finding = next(f for f in result.findings if "end-of-support" in f.id)
        assert support_finding.status == "pass"
        assert eos_finding.status == "pass"

    def test_cyclonedx_non_eos_milestone_passes_status_only(self) -> None:
        """A status-bearing milestone other than endOfSupport (e.g. endOfLife)
        satisfies the Support Status check but not the End-of-Support Date
        check, which requires the specific endOfSupport milestone.
        """
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    "properties": [
                        {"name": "cdx:lifecycle:milestone:endOfLife", "value": "2030-01-01"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 1
        support_finding = next(f for f in result.findings if "support-status" in f.id)
        eos_finding = next(f for f in result.findings if "end-of-support" in f.id)
        assert support_finding.status == "pass"
        assert eos_finding.status == "fail"

    def test_cyclonedx_missing_all_cle_data(self) -> None:
        """Test CycloneDX SBOM missing all CLE data."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    # No properties - missing CLE data
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 2  # Both CLE elements fail
        assert result.summary.pass_count == 7  # All NTIA elements pass

    def test_cyclonedx_empty_milestone_value_fails(self) -> None:
        """A milestone property with an empty string value must not count."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    "properties": [
                        {"name": "cdx:lifecycle:milestone:endOfSupport", "value": "   "},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        eos_finding = next(f for f in result.findings if "end-of-support" in f.id)
        assert support_finding.status == "fail"
        assert eos_finding.status == "fail"

    @pytest.mark.parametrize(
        "milestone_name",
        [
            "cdx:lifecycle:milestone:endOfSupport",
            "cdx:lifecycle:milestone:endOfLife",
            "cdx:lifecycle:milestone:endOfDevelopment",
            "cdx:lifecycle:milestone:endOfGuaranteedSupport",
            "cdx:lifecycle:milestone:endOfBusinessOperations",
        ],
    )
    def test_cyclonedx_any_status_milestone_satisfies_support_status(self, milestone_name: str) -> None:
        """Any status-bearing lifecycle milestone should satisfy the
        Software Support Status check, since the support level is
        derivable from the lifecycle position."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    "properties": [
                        {"name": milestone_name, "value": "2027-12-31"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        assert support_finding.status == "pass"

    def test_cyclonedx_non_status_milestone_does_not_satisfy_support_status(self) -> None:
        """A non-status milestone (generalAvailability, endOfMarketing,
        endOfProduction) should not be enough for Support Status alone."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    "properties": [
                        {"name": "cdx:lifecycle:milestone:generalAvailability", "value": "2020-01-01"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        eos_finding = next(f for f in result.findings if "end-of-support" in f.id)
        assert support_finding.status == "fail"
        assert eos_finding.status == "fail"

    def test_cyclonedx_multiple_components_mixed_cle(self) -> None:
        """Test CycloneDX SBOM with multiple components, some missing CLE data."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "component-with-cle",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/component-with-cle@1.0.0",
                    "properties": [
                        {"name": "cdx:lifecycle:milestone:endOfSupport", "value": "2027-12-31"},
                    ],
                },
                {
                    "name": "component-without-cle",
                    "version": "2.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/component-without-cle@2.0.0",
                    # Missing CLE properties
                },
            ],
            "dependencies": [
                {"ref": "pkg:pypi/component-with-cle@1.0.0", "dependsOn": []},
                {"ref": "pkg:pypi/component-without-cle@2.0.0", "dependsOn": []},
            ],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        # Both CLE elements should fail because one component is missing CLE data
        assert result.summary.fail_count == 2
        support_finding = next(f for f in result.findings if "support-status" in f.id)
        eos_finding = next(f for f in result.findings if "end-of-support" in f.id)
        assert support_finding.status == "fail"
        assert eos_finding.status == "fail"
        assert "component-without-cle" in support_finding.description
        assert "component-without-cle" in eos_finding.description

    def test_cyclonedx_ntia_elements_still_validated(self) -> None:
        """Test that NTIA elements are still validated alongside CLE elements."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    # Missing version, publisher, purl
                    "properties": [
                        {"name": "cdx:lifecycle:milestone:endOfSupport", "value": "2027-12-31"},
                    ],
                }
            ],
            # Missing dependencies
            "metadata": {
                # Missing authors/tools and timestamp
            },
        }

        result = self._assess_sbom(sbom_data)

        # NTIA elements fail: version, supplier, unique_ids, dependencies,
        # sbom-author, timestamp (6 total). Passing checks are component
        # name plus the 2 CLE elements.
        assert result.summary.fail_count == 6
        assert result.summary.pass_count == 3

    def _assess_sbom(self, sbom_data: dict) -> AssessmentResult:
        """Helper to write SBOM to temp file and assess it."""
        plugin = FDAMedicalDevicePlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test-sbom-id", Path(f.name))


class TestCycloneDXLegacyCleProperties:
    """Tests for backward compatibility with the deprecated cdx:cle:* names.

    Before this PR the plugin only recognised the non-standard
    cdx:cle:supportStatus / cdx:cle:endOfSupport properties. The primary
    path now uses the sanctioned cdx:lifecycle:milestone:* taxonomy, but
    the old names are still accepted so SBOMs emitted by earlier
    sbomify-action versions (or any other consumer that adopted the old
    convention) continue to pass.
    """

    def _assess_sbom(self, sbom_data: dict) -> AssessmentResult:
        plugin = FDAMedicalDevicePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test-sbom-id", Path(f.name))

    def test_legacy_cdx_cle_properties_still_pass(self) -> None:
        """A component using only the deprecated cdx:cle:* names should
        still satisfy both CLE checks."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example",
                    "version": "1.0.0",
                    "publisher": "Corp",
                    "purl": "pkg:pypi/example@1.0.0",
                    "properties": [
                        {"name": "cdx:cle:supportStatus", "value": "active"},
                        {"name": "cdx:cle:endOfSupport", "value": "2027-12-31"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }
        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert len(cle_findings) == 2
        assert all(f.status == "pass" for f in cle_findings), (
            f"Legacy cdx:cle:* properties should still pass: {[(f.id, f.status) for f in cle_findings]}"
        )

    def test_legacy_cdx_cle_endOfSupport_alone_passes_both_checks(self) -> None:
        """Legacy cdx:cle:endOfSupport alone (without supportStatus) still
        implies enough lifecycle data to derive support status."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example",
                    "version": "1.0.0",
                    "publisher": "Corp",
                    "purl": "pkg:pypi/example@1.0.0",
                    "properties": [
                        {"name": "cdx:cle:endOfSupport", "value": "2027-12-31"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }
        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert all(f.status == "pass" for f in cle_findings)

    def test_legacy_invalid_support_status_value_not_counted(self) -> None:
        """An invalid enum value on cdx:cle:supportStatus must not count
        (preserves the original enum validation)."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example",
                    "version": "1.0.0",
                    "publisher": "Corp",
                    "purl": "pkg:pypi/example@1.0.0",
                    "properties": [
                        {"name": "cdx:cle:supportStatus", "value": "not-a-valid-status"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }
        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert all(f.status == "fail" for f in cle_findings)

    @pytest.mark.parametrize("spec_version", ["1.3", "1.4", "1.5", "1.6", "1.7"])
    def test_cle_checks_work_across_cdx_spec_versions(self, spec_version: str) -> None:
        """The sanctioned cdx:lifecycle:milestone:* properties should be
        honoured across every CycloneDX spec version sbomify accepts
        (1.3 to 1.7). Component.properties has existed since 1.3."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": spec_version,
            "components": [
                {
                    "name": "example",
                    "version": "1.0.0",
                    "publisher": "Corp",
                    "purl": "pkg:pypi/example@1.0.0",
                    "properties": [
                        {"name": "cdx:lifecycle:milestone:endOfSupport", "value": "2027-12-31"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }
        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert all(f.status == "pass" for f in cle_findings), (
            f"CLE checks failed on CycloneDX {spec_version}: {[(f.id, f.status) for f in cle_findings]}"
        )

    def test_mixed_legacy_and_sanctioned_properties_pass(self) -> None:
        """Components mixing legacy and sanctioned property names should
        still pass — either is sufficient."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "legacy-component",
                    "version": "1.0.0",
                    "publisher": "Corp",
                    "purl": "pkg:pypi/legacy@1.0.0",
                    "properties": [
                        {"name": "cdx:cle:endOfSupport", "value": "2027-12-31"},
                    ],
                },
                {
                    "name": "sanctioned-component",
                    "version": "2.0.0",
                    "publisher": "Corp",
                    "purl": "pkg:pypi/sanctioned@2.0.0",
                    "properties": [
                        {"name": "cdx:lifecycle:milestone:endOfSupport", "value": "2028-06-30"},
                    ],
                },
            ],
            "dependencies": [
                {"ref": "pkg:pypi/legacy@1.0.0", "dependsOn": []},
                {"ref": "pkg:pypi/sanctioned@2.0.0", "dependsOn": []},
            ],
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }
        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert all(f.status == "pass" for f in cle_findings)


class TestCycloneDXLifecycleFallback:
    """Tests for metadata-level lifecycle property fallback.

    Per FDA V.A.4.b and the CycloneDX property taxonomy, a doc-level
    cdx:lifecycle:milestone:endOfSupport describes only the BOM subject
    (the root component) — it does NOT imply support coverage for the
    dependencies listed in components[]. Each dependency must carry its
    own CLE data or fail the per-component check.
    """

    def _assess_sbom(self, sbom_data: dict) -> AssessmentResult:
        plugin = FDAMedicalDevicePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test-sbom-id", Path(f.name))

    def test_dependency_fails_even_with_doc_level_lifecycle(self) -> None:
        """Doc-level lifecycle milestone must not blanket-pass dependencies.

        Regression guard for the pre-fix behavior where a single doc-level
        cdx:lifecycle:milestone:endOfSupport caused every component in
        components[] to auto-pass both CLE checks. That behavior hid real
        per-component data gaps that FDA V.A.4.b requires surfaced.
        """
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "django",
                    "version": "5.0.0",
                    "publisher": "Django Software Foundation",
                    "purl": "pkg:pypi/django@5.0.0",
                    "bom-ref": "pkg:pypi/django@5.0.0",
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/django@5.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "component": {
                    "bom-ref": "pkg:pypi/my-app@1.0.0",
                    "name": "my-app",
                    "version": "1.0.0",
                    "type": "application",
                },
                "properties": [
                    {"name": "cdx:lifecycle:milestone:endOfSupport", "value": "2027-12-31"},
                ],
            },
        }
        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert len(cle_findings) == 2
        assert all(f.status == "fail" for f in cle_findings), (
            f"Dependencies must not pass via doc-level fallback: {[(f.id, f.status) for f in cle_findings]}"
        )
        for finding in cle_findings:
            assert finding.description and "django" in finding.description

    def test_root_component_passes_with_doc_level_lifecycle(self) -> None:
        """When the root subject is listed in components[], the doc-level
        milestone is a valid fallback ONLY for that root component."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "my-app",
                    "version": "1.0.0",
                    "publisher": "My Corp",
                    "purl": "pkg:pypi/my-app@1.0.0",
                    "bom-ref": "pkg:pypi/my-app@1.0.0",
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/my-app@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "component": {
                    "bom-ref": "pkg:pypi/my-app@1.0.0",
                    "name": "my-app",
                    "version": "1.0.0",
                    "type": "application",
                },
                "properties": [
                    {"name": "cdx:lifecycle:milestone:endOfSupport", "value": "2027-12-31"},
                ],
            },
        }
        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert len(cle_findings) == 2
        assert all(f.status == "pass" for f in cle_findings), (
            f"Root component should pass via narrow doc-level fallback: {[(f.id, f.status) for f in cle_findings]}"
        )

    def test_root_in_metadata_only_dependencies_still_fail(self) -> None:
        """Root listed only in metadata.component (not components[]) must not
        make dependencies auto-pass via doc-level lifecycle.

        This is the real-world case: the subject component is described in
        metadata.component and each dependency sits in components[]. The
        dependencies have no CLE data and must fail.
        """
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "django",
                    "version": "5.0.0",
                    "publisher": "DSF",
                    "purl": "pkg:pypi/django@5.0.0",
                    "bom-ref": "pkg:pypi/django@5.0.0",
                },
                {
                    "name": "requests",
                    "version": "2.32.0",
                    "publisher": "Python Software Foundation",
                    "purl": "pkg:pypi/requests@2.32.0",
                    "bom-ref": "pkg:pypi/requests@2.32.0",
                },
            ],
            "dependencies": [
                {"ref": "pkg:pypi/django@5.0.0", "dependsOn": []},
                {"ref": "pkg:pypi/requests@2.32.0", "dependsOn": []},
            ],
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2023-01-01T00:00:00Z",
                "component": {
                    "bom-ref": "pkg:pypi/my-app@1.0.0",
                    "name": "my-app",
                    "version": "1.0.0",
                    "type": "application",
                },
                "properties": [
                    {"name": "cdx:lifecycle:milestone:endOfSupport", "value": "2027-12-31"},
                ],
            },
        }
        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert len(cle_findings) == 2
        assert all(f.status == "fail" for f in cle_findings)
        for finding in cle_findings:
            assert finding.description and "django" in finding.description
            assert finding.description and "requests" in finding.description

    def test_component_with_own_cle_passes(self) -> None:
        """A component carrying its own cdx:lifecycle:milestone:* properties
        should pass the CLE checks regardless of doc-level data."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "django",
                    "version": "5.0.0",
                    "publisher": "DSF",
                    "purl": "pkg:pypi/django@5.0.0",
                    "bom-ref": "pkg:pypi/django@5.0.0",
                    "properties": [
                        {"name": "cdx:lifecycle:milestone:endOfSupport", "value": "2027-12-31"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/django@5.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }
        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert len(cle_findings) == 2
        assert all(f.status == "pass" for f in cle_findings)

    def test_no_lifecycle_anywhere_fails_cle(self) -> None:
        """Without any lifecycle data, CLE checks should fail."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example",
                    "version": "1.0.0",
                    "publisher": "Corp",
                    "purl": "pkg:pypi/example@1.0.0",
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }
        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert len(cle_findings) == 2, f"Expected 2 CLE findings, got {len(cle_findings)}"
        assert all(f.status == "fail" for f in cle_findings)


class TestSPDXLifecycleFallback:
    """Tests for SPDX document-level lifecycle annotation fallback.

    Mirrors TestCycloneDXLifecycleFallback for SPDX: a document-level
    annotation describing support lifecycle applies only to the DESCRIBES
    target (the root subject), not to every package in packages[].
    """

    def _assess_sbom(self, sbom_data: dict) -> AssessmentResult:
        plugin = FDAMedicalDevicePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test-sbom-id", Path(f.name))

    def test_spdx_dependency_fails_with_only_doc_level_annotation(self) -> None:
        """A document-level CLE annotation must not blanket-pass dependencies."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "my-app",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/my-app",
            "creationInfo": {
                "created": "2023-01-01T00:00:00Z",
                "creators": ["Organization: Example Corp"],
            },
            "documentDescribes": ["SPDXRef-Package-my-app"],
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-my-app",
                    "name": "my-app",
                    "versionInfo": "1.0.0",
                    "supplier": "Organization: Example Corp",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/my-app@1.0.0",
                        }
                    ],
                },
                {
                    "SPDXID": "SPDXRef-Package-django",
                    "name": "django",
                    "versionInfo": "5.0.0",
                    "supplier": "Organization: DSF",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/django@5.0.0",
                        }
                    ],
                },
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-Package-my-app",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package-django",
                }
            ],
            "annotations": [
                {
                    "annotationType": "OTHER",
                    "annotator": "Tool: sbomify",
                    "annotationDate": "2023-01-01T00:00:00Z",
                    "comment": "cle:supportStatus=active cle:endOfSupport=2027-12-31",
                }
            ],
        }
        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert len(cle_findings) == 2
        # Doc-level fallback should cover the root (my-app) for both checks,
        # but dependencies must be judged on their own data.
        for finding in cle_findings:
            assert finding.status == "fail", f"Expected fail for {finding.id}, got {finding.status}"
            fail_list = (finding.description or "").split("Missing for:")[-1]
            assert "django" in fail_list, f"Expected django in {finding.id} fail list: {fail_list}"
            assert "my-app" not in fail_list, f"Root 'my-app' should not be in {finding.id} fail list: {fail_list}"

    def test_spdx_doc_annotation_targeting_specific_package_does_not_fallback_to_root(self) -> None:
        """Per SPDX 2.3 §12, a top-level annotation with spdxElementId pointing
        at a specific package describes that package — not the document. The
        narrow root fallback must therefore ignore such annotations and must
        not grant the root component a pass via someone else's annotation.
        """
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "doc",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/doc",
            "creationInfo": {
                "created": "2023-01-01T00:00:00Z",
                "creators": ["Organization: Corp"],
            },
            "documentDescribes": ["SPDXRef-Package-root"],
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-root",
                    "name": "root",
                    "versionInfo": "1.0.0",
                    "supplier": "Organization: Corp",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/root@1.0.0",
                        }
                    ],
                },
                {
                    "SPDXID": "SPDXRef-Package-dep",
                    "name": "dep",
                    "versionInfo": "1.0.0",
                    "supplier": "Organization: Corp",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/dep@1.0.0",
                        }
                    ],
                },
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Package-root",
                }
            ],
            "annotations": [
                {
                    "annotationType": "OTHER",
                    "annotator": "Tool: sbomify",
                    "annotationDate": "2023-01-01T00:00:00Z",
                    "spdxElementId": "SPDXRef-Package-dep",
                    "comment": "cle:supportStatus=active cle:endOfSupport=2027-12-31",
                }
            ],
        }
        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        for finding in cle_findings:
            assert finding.status == "fail"
            fail_list = (finding.description or "").split("Missing for:")[-1]
            assert "root" in fail_list, (
                f"Root must fail {finding.id}: doc annotation targets dep, not document. Got: {finding.description}"
            )

    def test_spdx_doc_annotation_with_explicit_document_subject_passes_root(self) -> None:
        """A top-level annotation with spdxElementId=SPDXRef-DOCUMENT behaves
        identically to one with no spdxElementId — both describe the document
        and feed the root fallback."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "doc",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/doc",
            "creationInfo": {
                "created": "2023-01-01T00:00:00Z",
                "creators": ["Organization: Corp"],
            },
            "documentDescribes": ["SPDXRef-Package-root"],
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-root",
                    "name": "root",
                    "versionInfo": "1.0.0",
                    "supplier": "Organization: Corp",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/root@1.0.0",
                        }
                    ],
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Package-root",
                }
            ],
            "annotations": [
                {
                    "annotationType": "OTHER",
                    "annotator": "Tool: sbomify",
                    "annotationDate": "2023-01-01T00:00:00Z",
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "comment": "cle:supportStatus=active cle:endOfSupport=2027-12-31",
                }
            ],
        }
        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert all(f.status == "pass" for f in cle_findings)

    def test_spdx_root_via_describes_relationship_fallback(self) -> None:
        """When documentDescribes is absent, the root is inferred from a
        DESCRIBES relationship with spdxElementId == SPDXRef-DOCUMENT."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "my-app",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/my-app",
            "creationInfo": {
                "created": "2023-01-01T00:00:00Z",
                "creators": ["Organization: Example Corp"],
            },
            # No documentDescribes — root must be inferred from relationships.
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-my-app",
                    "name": "my-app",
                    "versionInfo": "1.0.0",
                    "supplier": "Organization: Example Corp",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/my-app@1.0.0",
                        }
                    ],
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Package-my-app",
                }
            ],
            "annotations": [
                {
                    "annotationType": "OTHER",
                    "annotator": "Tool: sbomify",
                    "annotationDate": "2023-01-01T00:00:00Z",
                    "spdxElementId": "SPDXRef-Package-my-app",
                    "comment": "cle:supportStatus=active cle:endOfSupport=2027-12-31",
                }
            ],
        }
        result = self._assess_sbom(sbom_data)
        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert all(f.status == "pass" for f in cle_findings)

    def test_spdx_unanchored_annotation_without_root_rejected(self) -> None:
        """When the document declares no DESCRIBES target AND an annotation
        has empty spdxElementId, the annotation is unanchored. The narrow
        fallback must reject it so a crafted SBOM cannot inflate the
        compliance score.
        """
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "attack",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/x",
            "creationInfo": {
                "created": "2023-01-01T00:00:00Z",
                "creators": ["Organization: Anon"],
            },
            # No documentDescribes, no DESCRIBES relationship.
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-x",
                    "name": "x",
                    "versionInfo": "1.0.0",
                    "supplier": "Organization: Anon",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/x@1.0.0",
                        }
                    ],
                }
            ],
            "annotations": [
                {
                    "annotationType": "OTHER",
                    "annotator": "Tool: sbomify",
                    "annotationDate": "2023-01-01T00:00:00Z",
                    # No spdxElementId -- unanchored.
                    "comment": "cle:supportStatus=active cle:endOfSupport=2027-12-31",
                }
            ],
        }
        result = self._assess_sbom(sbom_data)
        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert all(f.status == "fail" for f in cle_findings)

    def test_spdx_root_passes_with_doc_level_annotation(self) -> None:
        """When the SPDX DESCRIBES target has a doc-level CLE annotation,
        that target passes. Other packages still need their own data."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "my-app",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/my-app",
            "creationInfo": {
                "created": "2023-01-01T00:00:00Z",
                "creators": ["Organization: My Corp"],
            },
            "documentDescribes": ["SPDXRef-Package-my-app"],
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-my-app",
                    "name": "my-app",
                    "versionInfo": "1.0.0",
                    "supplier": "Organization: My Corp",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/my-app@1.0.0",
                        }
                    ],
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Package-my-app",
                }
            ],
            "annotations": [
                {
                    "annotationType": "OTHER",
                    "annotator": "Tool: sbomify",
                    "annotationDate": "2023-01-01T00:00:00Z",
                    "comment": "cle:supportStatus=active cle:endOfSupport=2027-12-31",
                }
            ],
        }
        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert len(cle_findings) == 2
        assert all(f.status == "pass" for f in cle_findings), (
            f"Root SPDX package should pass via doc-level annotation: {[(f.id, f.status) for f in cle_findings]}"
        )


class TestSPDXValidation:
    """Tests for SPDX SBOM validation."""

    def test_compliant_spdx_sbom_with_cle(self) -> None:
        """Test validation of a fully compliant SPDX SBOM with CLE data."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/example-package@1.0.0",
                        }
                    ],
                    "validUntilDate": "2027-12-31T00:00:00Z",
                    "annotations": [
                        {
                            "annotationType": "OTHER",
                            "comment": "cle:supportStatus=active",
                            "annotator": "Tool: sbomify",
                            "annotationDate": "2023-01-01T00:00:00Z",
                        }
                    ],
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package",
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 0
        assert result.summary.pass_count == 9  # 7 NTIA + 2 CLE elements

    def test_spdx_2_2_compliant_sbom_matches_2_3_behavior(self) -> None:
        """FDA accepts SPDX 2.2 uploads identically to SPDX 2.3. The shared
        schema module routes both through the same parsing + CLE logic;
        pin the behaviour so the SPDX 2.2 on-ramp stays open as the plugin
        evolves. The base document is fully compliant; the 2.2 variant
        satisfies 2.2-specific package fields (copyrightText, licence
        fields, documentNamespace).
        """
        shared_pkg = {
            "SPDXID": "SPDXRef-Package",
            "name": "example-package",
            "supplier": "Organization: Example Corp",
            "versionInfo": "1.0.0",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": "pkg:pypi/example-package@1.0.0",
                }
            ],
            "validUntilDate": "2027-12-31T00:00:00Z",
            "downloadLocation": "NOASSERTION",
            "copyrightText": "NOASSERTION",
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "annotations": [
                {
                    "annotationType": "OTHER",
                    "comment": "cle:supportStatus=active",
                    "annotator": "Tool: sbomify",
                    "annotationDate": "2023-01-01T00:00:00Z",
                }
            ],
        }

        def _make(version: str) -> dict:
            return {
                "spdxVersion": version,
                "SPDXID": "SPDXRef-DOCUMENT",
                "dataLicense": "CC0-1.0",
                "name": "example-sbom",
                "documentNamespace": "https://example.com/sbom/parity-test",
                "packages": [dict(shared_pkg)],
                "relationships": [
                    {
                        "spdxElementId": "SPDXRef-DOCUMENT",
                        "relationshipType": "DEPENDS_ON",
                        "relatedSpdxElement": "SPDXRef-Package",
                    }
                ],
                "creationInfo": {
                    "creators": ["Tool: example-tool"],
                    "created": "2023-01-01T00:00:00Z",
                },
            }

        result_22 = self._assess_sbom(_make("SPDX-2.2"))
        result_23 = self._assess_sbom(_make("SPDX-2.3"))

        findings_22 = {f.id: f.status for f in result_22.findings}
        findings_23 = {f.id: f.status for f in result_23.findings}
        assert findings_22 == findings_23, f"SPDX 2.2 vs 2.3 divergence for FDA: 22={findings_22}, 23={findings_23}"
        # Both must be fully compliant — verifying equality alone would
        # pass trivially if BOTH were broken in the same way.
        assert result_22.summary.fail_count == 0
        assert result_22.summary.pass_count == 9

    def test_spdx_missing_valid_until_date(self) -> None:
        """Test SPDX SBOM missing validUntilDate for end-of-support."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/example-package@1.0.0",
                        }
                    ],
                    # Missing validUntilDate
                    "annotations": [
                        {
                            "annotationType": "OTHER",
                            "comment": "cle:supportStatus=active",
                            "annotator": "Tool: sbomify",
                            "annotationDate": "2023-01-01T00:00:00Z",
                        }
                    ],
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package",
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 1
        eos_finding = next(f for f in result.findings if "end-of-support" in f.id)
        assert eos_finding.status == "fail"

    def test_spdx_missing_support_status_annotation(self) -> None:
        """Test SPDX SBOM missing CLE support status annotation."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/example-package@1.0.0",
                        }
                    ],
                    "validUntilDate": "2027-12-31T00:00:00Z",
                    # Missing annotations with support status
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package",
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 1
        support_finding = next(f for f in result.findings if "support-status" in f.id)
        assert support_finding.status == "fail"

    def test_spdx_support_status_in_document_annotations(self) -> None:
        """Test SPDX SBOM with support status in document-level annotations."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/example-package@1.0.0",
                        }
                    ],
                    "validUntilDate": "2027-12-31T00:00:00Z",
                }
            ],
            "annotations": [
                {
                    "spdxElementId": "SPDXRef-Package",
                    "annotationType": "OTHER",
                    "comment": "cle:supportStatus=deprecated",
                    "annotator": "Tool: sbomify",
                    "annotationDate": "2023-01-01T00:00:00Z",
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package",
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        assert support_finding.status == "pass"

    def test_spdx_wrong_annotation_type_ignored(self) -> None:
        """Test SPDX SBOM with wrong annotation type is not counted as support status."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package",
                    "name": "example-package",
                    "supplier": "Organization: Example Corp",
                    "versionInfo": "1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/example-package@1.0.0",
                        }
                    ],
                    "validUntilDate": "2027-12-31T00:00:00Z",
                    "annotations": [
                        {
                            "annotationType": "REVIEW",  # Wrong type - should be OTHER
                            "comment": "cle:supportStatus=active",
                            "annotator": "Tool: sbomify",
                            "annotationDate": "2023-01-01T00:00:00Z",
                        }
                    ],
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Package",
                }
            ],
            "creationInfo": {
                "creators": ["Tool: example-tool"],
                "created": "2023-01-01T00:00:00Z",
            },
        }

        result = self._assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        assert support_finding.status == "fail"  # Wrong annotation type is not valid

    def test_malformed_reference_type_as_list(self) -> None:
        """Regression: referenceType as list should not crash."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Pkg",
                    "name": "test",
                    "supplier": "Org: Test",
                    "versionInfo": "1.0",
                    "externalRefs": [{"referenceType": ["purl"]}],
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": "SPDXRef-Pkg",
                }
            ],
            "creationInfo": {"creators": ["Tool: test"], "created": "2023-01-01T00:00:00Z"},
        }
        result = self._assess_sbom(sbom_data)
        assert result.summary.error_count == 0

    def test_malformed_relationship_type_as_list(self) -> None:
        """Regression: relationshipType as list should not crash."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Pkg",
                    "name": "test",
                    "supplier": "Org: T",
                    "versionInfo": "1.0",
                    "purl": "pkg:pypi/t@1",
                }
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": ["DEPENDS_ON"],
                    "relatedSpdxElement": "SPDXRef-Pkg",
                }
            ],
            "creationInfo": {"creators": ["Tool: test"], "created": "2023-01-01T00:00:00Z"},
        }
        result = self._assess_sbom(sbom_data)
        assert result.summary.error_count == 0
        dep_finding = next(f for f in result.findings if "dependency" in f.id)
        assert dep_finding.status == "fail"

    def _assess_sbom(self, sbom_data: dict) -> AssessmentResult:
        """Helper to write SBOM to temp file and assess it."""
        plugin = FDAMedicalDevicePlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test-sbom-id", Path(f.name))


class TestErrorHandling:
    """Tests for error handling in the plugin."""

    def test_invalid_json(self) -> None:
        """Test handling of invalid JSON file."""
        plugin = FDAMedicalDevicePlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{ invalid json }")
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.summary.error_count == 1
        assert result.metadata.get("error") is True

    def test_unknown_format(self) -> None:
        """Test handling of unknown SBOM format."""
        plugin = FDAMedicalDevicePlugin()
        sbom_data = {"some": "data", "without": "format indicators"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.summary.error_count == 1
        assert "format" in result.findings[0].description.lower()

    def test_empty_components(self) -> None:
        """Test handling of SBOM with empty components list."""
        plugin = FDAMedicalDevicePlugin()
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [],
            "dependencies": [],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        # With empty components, per-component checks pass (nothing to fail)
        # but dependencies should fail
        dep_finding = next(f for f in result.findings if "dependency" in f.id)
        assert dep_finding.status == "fail"


class TestFindingDetails:
    """Tests for finding details and remediation suggestions."""

    def test_findings_have_remediation(self) -> None:
        """Test that failed findings include remediation suggestions."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [{"name": "example"}],  # Missing most required fields
            "metadata": {},
        }

        plugin = FDAMedicalDevicePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        for finding in result.findings:
            if finding.status == "fail":
                assert finding.remediation is not None, f"Finding {finding.id} should have remediation"

    def test_findings_have_standard_metadata(self) -> None:
        """Test that findings include standard version metadata."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example",
                    "version": "1.0.0",
                    "publisher": "Example",
                    "purl": "pkg:npm/example@1.0.0",
                    "properties": [
                        {"name": "cdx:lifecycle:milestone:endOfSupport", "value": "2027-12-31"},
                    ],
                }
            ],
            "dependencies": [{"ref": "pkg:npm/example@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Author"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        plugin = FDAMedicalDevicePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        for finding in result.findings:
            assert finding.metadata is not None
            assert finding.metadata.get("standard") == "FDA"
            assert finding.metadata.get("standard_version") == "2025-06"
            # Check element source is correctly set
            if "cle" in finding.id:
                assert finding.metadata.get("element_source") == "FDA-CLE"
            else:
                assert finding.metadata.get("element_source") == "NTIA"

    def test_result_includes_standard_info(self) -> None:
        """Test that assessment result includes standard reference information."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [],
            "metadata": {"timestamp": "2023-01-01T00:00:00Z"},
        }

        plugin = FDAMedicalDevicePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        assert result.metadata["standard_name"] == plugin.STANDARD_NAME
        assert result.metadata["standard_version"] == plugin.STANDARD_VERSION
        assert result.metadata["standard_url"] == plugin.STANDARD_URL

    def test_cle_remediation_mentions_github_action(self) -> None:
        """Test that CLE element remediation mentions the sbomify GitHub Action."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "example-component",
                    "version": "1.0.0",
                    "publisher": "Example Corp",
                    "purl": "pkg:pypi/example-component@1.0.0",
                    # Missing CLE properties
                }
            ],
            "dependencies": [{"ref": "pkg:pypi/example-component@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        plugin = FDAMedicalDevicePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        eos_finding = next(f for f in result.findings if "end-of-support" in f.id)

        assert "sbomify GitHub Action" in support_finding.remediation
        assert "sbomify GitHub Action" in eos_finding.remediation

    def test_failure_list_includes_all_components(self) -> None:
        """Test that failure details include all failing components."""
        # Create SBOM with 10 components missing CLE data
        components = [
            {
                "name": f"component-{i}",
                "version": "1.0.0",
                "publisher": "Example Corp",
                "purl": f"pkg:pypi/component-{i}@1.0.0",
            }
            for i in range(10)
        ]

        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": components,
            "dependencies": [{"ref": c["purl"], "dependsOn": []} for c in components],
            "metadata": {
                "authors": [{"name": "Example Developer"}],
                "timestamp": "2023-01-01T00:00:00Z",
            },
        }

        plugin = FDAMedicalDevicePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            result = plugin.assess("test-sbom-id", Path(f.name))

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        # All 10 components should be listed (no truncation)
        for i in range(10):
            assert f"component-{i}" in support_finding.description


def _create_base_spdx3_sbom() -> dict:
    """Create a base compliant SPDX 3.0 SBOM for FDA testing."""
    return {
        "@context": "https://spdx.org/rdf/3.0.1/spdx-context.jsonld",
        "@graph": [
            {
                "type": "CreationInfo",
                "@id": "_:creationInfo",
                "specVersion": "3.0.1",
                "created": "2024-01-15T12:00:00Z",
                "createdBy": ["SPDXRef-Creator"],
            },
            {
                "type": "Organization",
                "spdxId": "SPDXRef-Creator",
                "name": "SBOM Creator Corp",
                "externalIdentifiers": [{"externalIdentifierType": "email", "identifier": "creator@example.com"}],
            },
            {
                "type": "Organization",
                "spdxId": "SPDXRef-Supplier",
                "name": "Supplier Corp",
                "externalIdentifiers": [{"externalIdentifierType": "email", "identifier": "supplier@example.com"}],
            },
            {
                "type": "software_Package",
                "spdxId": "SPDXRef-Package-1",
                "name": "example-package",
                "software_packageVersion": "1.0.0",
                "originatedBy": ["SPDXRef-Supplier"],
                "software_validUntilDate": "2025-12-31T00:00:00Z",
                "externalIdentifiers": [
                    {"externalIdentifierType": "packageURL", "identifier": "pkg:pypi/example@1.0.0"}
                ],
            },
            {
                "type": "Relationship",
                "spdxId": "SPDXRef-Rel-1",
                "from": "SPDXRef-Package-1",
                "relationshipType": "dependsOn",
                "to": [],
            },
            {
                "type": "Annotation",
                "spdxId": "SPDXRef-Annotation-1",
                "subject": "SPDXRef-Package-1",
                "statement": "cle:supportStatus=active",
            },
        ],
    }


class TestSPDX3Validation:
    """Tests for SPDX 3.0 SBOM validation against FDA requirements."""

    def test_compliant_spdx3_sbom(self) -> None:
        """Test validation of a compliant SPDX 3.0 SBOM."""
        sbom_data = _create_base_spdx3_sbom()
        result = self._assess_sbom(sbom_data)

        assert result.summary.fail_count == 0
        assert result.summary.pass_count == 9  # 7 NTIA + 2 CLE
        assert result.summary.total_findings == 9

    def test_spdx3_format_detection(self) -> None:
        """Test that SPDX 3.0 format is correctly detected."""
        sbom_data = _create_base_spdx3_sbom()
        result = self._assess_sbom(sbom_data)

        assert result.metadata["sbom_format"] == "spdx3"

    def test_spdx3_missing_supplier(self) -> None:
        """Test SPDX 3.0 SBOM missing supplier (originatedBy)."""
        sbom_data = _create_base_spdx3_sbom()
        del sbom_data["@graph"][3]["originatedBy"]

        result = self._assess_sbom(sbom_data)

        supplier_finding = next(f for f in result.findings if "supplier-name" in f.id)
        assert supplier_finding.status == "fail"

    def test_spdx3_missing_version(self) -> None:
        """Test SPDX 3.0 SBOM missing version."""
        sbom_data = _create_base_spdx3_sbom()
        del sbom_data["@graph"][3]["software_packageVersion"]

        result = self._assess_sbom(sbom_data)

        version_finding = next(f for f in result.findings if "version" in f.id)
        assert version_finding.status == "fail"

    def test_spdx3_missing_support_status(self) -> None:
        """Test SPDX 3.0 SBOM missing CLE support status annotation."""
        sbom_data = _create_base_spdx3_sbom()
        # Remove annotation (last element in graph)
        sbom_data["@graph"] = [e for e in sbom_data["@graph"] if e.get("type") != "Annotation"]

        result = self._assess_sbom(sbom_data)

        support_finding = next(f for f in result.findings if "support-status" in f.id)
        assert support_finding.status == "fail"

    def test_spdx3_missing_end_of_support(self) -> None:
        """Test SPDX 3.0 SBOM missing end-of-support date (software_validUntilDate)."""
        sbom_data = _create_base_spdx3_sbom()
        del sbom_data["@graph"][3]["software_validUntilDate"]

        result = self._assess_sbom(sbom_data)

        eos_finding = next(f for f in result.findings if "end-of-support" in f.id)
        assert eos_finding.status == "fail"

    def test_spdx3_valid_support_status_values(self) -> None:
        """Test all valid CLE support status values."""
        for status in ["active", "deprecated", "eol", "abandoned", "unknown"]:
            sbom_data = _create_base_spdx3_sbom()
            # Update the annotation statement
            for elem in sbom_data["@graph"]:
                if elem.get("type") == "Annotation":
                    elem["statement"] = f"cle:supportStatus={status}"

            result = self._assess_sbom(sbom_data)

            support_finding = next(f for f in result.findings if "support-status" in f.id)
            assert support_finding.status == "pass", f"Status '{status}' should be valid"

    def test_spdx3_missing_sbom_author(self) -> None:
        """Test SPDX 3.0 SBOM missing SBOM author."""
        sbom_data = _create_base_spdx3_sbom()
        sbom_data["@graph"][0]["createdBy"] = []

        result = self._assess_sbom(sbom_data)

        author_finding = next(f for f in result.findings if "sbom-author" in f.id)
        assert author_finding.status == "fail"

    def test_spdx3_missing_dependencies(self) -> None:
        """Test SPDX 3.0 SBOM with no dependency relationships."""
        sbom_data = _create_base_spdx3_sbom()
        sbom_data["@graph"] = [
            e for e in sbom_data["@graph"] if e.get("relationshipType") not in ("dependsOn", "contains")
        ]

        result = self._assess_sbom(sbom_data)

        dep_finding = next(f for f in result.findings if "dependency-relationship" in f.id)
        assert dep_finding.status == "fail"

    def test_spdx3_doc_level_annotation_passes_root_only(self) -> None:
        """A doc-level Annotation whose subject is the SpdxDocument lets the
        root package inherit CLE data; dependencies without their own data
        must still fail (parity with the SPDX 2.3 narrow fallback).

        The fixture adds a non-root dependency package so the test actually
        guards the intended regression: if the doc-level fallback leaked to
        non-root packages, the dep's CLE findings would pass too. The
        Annotation's subject is the SpdxDocument spdxId (not the rootElement
        id) so this also exercises the "subject == doc id" arm of
        spdx3_annotation_subject_matches.
        """
        sbom_data = _create_base_spdx3_sbom()
        # Remove the package-level annotation and software_validUntilDate so
        # the only CLE signal is a doc-level annotation.
        sbom_data["@graph"] = [e for e in sbom_data["@graph"] if e.get("type") != "Annotation"]
        for e in sbom_data["@graph"]:
            if e.get("type") == "software_Package":
                e.pop("software_validUntilDate", None)
        # Introduce a dependency package with no CLE data and a dependsOn
        # relationship so the root's fallback does not accidentally shield
        # unrelated packages.
        sbom_data["@graph"].append(
            {
                "type": "software_Package",
                "spdxId": "SPDXRef-Package-2",
                "name": "dep-package",
                "software_packageVersion": "2.0.0",
                "originatedBy": ["SPDXRef-Supplier"],
                "externalIdentifiers": [
                    {"externalIdentifierType": "packageURL", "identifier": "pkg:pypi/dep@2.0.0"}
                ],
            }
        )
        for e in sbom_data["@graph"]:
            if e.get("type") == "Relationship" and e.get("from") == "SPDXRef-Package-1":
                e["to"] = ["SPDXRef-Package-2"]
        sbom_data["@graph"].append(
            {
                "type": "SpdxDocument",
                "spdxId": "SPDXRef-Document",
                "rootElement": ["SPDXRef-Package-1"],
            }
        )
        sbom_data["@graph"].append(
            {
                "type": "Annotation",
                "spdxId": "SPDXRef-Annotation-Doc",
                # Subject is the SpdxDocument's own spdxId — true doc scope.
                "subject": "SPDXRef-Document",
                "statement": "cle:supportStatus=active cle:endOfSupport=2027-12-31",
            }
        )

        result = self._assess_sbom(sbom_data)

        # Dependency has no CLE data, so the aggregated CLE findings MUST
        # fail — and the failure must name the dep, not the root, proving
        # the fallback only inflated the root.
        support = next(f for f in result.findings if "support-status" in f.id)
        eos = next(f for f in result.findings if "end-of-support" in f.id)
        assert support.status == "fail", "dep should fail support-status"
        assert eos.status == "fail", "dep should fail end-of-support"
        assert "dep-package" in support.description, support.description
        assert "dep-package" in eos.description, eos.description
        assert "example-package" not in support.description, (
            f"root must inherit doc-level annotation, not be listed as failing: {support.description}"
        )
        assert "example-package" not in eos.description, (
            f"root must inherit doc-level end-of-support, not be listed as failing: {eos.description}"
        )

    def _build_spdx3_with_empty_subject_annotation(self, *, root_elements: list[str] | None) -> dict:
        """Build an SPDX 3.x fixture with an SpdxDocument (optionally carrying
        a rootElement) and an empty-subject Annotation that would supply
        doc-level CLE tokens. Keeps existing non-Annotation, non-SpdxDocument
        elements so the base CreationInfo/Organization/Package/Relationship
        survive but no conflicting document/annotation pre-exists.
        """
        sbom_data = _create_base_spdx3_sbom()
        sbom_data["@graph"] = [e for e in sbom_data["@graph"] if e.get("type") not in {"Annotation", "SpdxDocument"}]
        for e in sbom_data["@graph"]:
            if e.get("type") == "software_Package":
                e.pop("software_validUntilDate", None)
        spdx_document: dict[str, Any] = {"type": "SpdxDocument", "spdxId": "SPDXRef-Document"}
        if root_elements is not None:
            spdx_document["rootElement"] = root_elements
        sbom_data["@graph"].append(spdx_document)
        sbom_data["@graph"].append(
            {
                "type": "Annotation",
                "spdxId": "SPDXRef-Annotation-Empty",
                # no `subject` — empty
                "statement": "cle:supportStatus=active cle:endOfSupport=2027-12-31",
            }
        )
        return sbom_data

    def test_spdx3_empty_subject_without_rootelement_rejected(self) -> None:
        """An SPDX 3.x SBOM with an SpdxDocument element but NO rootElement
        must NOT treat an empty-subject annotation as document-scoped.

        Symmetric to the SPDX 2.x rule: without a declared BOM subject
        (rootElement in 3.x, DESCRIBES target in 2.x) an empty-subject
        annotation is unanchored and cannot inflate the compliance score.
        """
        sbom_data = self._build_spdx3_with_empty_subject_annotation(root_elements=None)

        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert all(f.status == "fail" for f in cle_findings), (
            "Empty-subject annotation must be rejected when no rootElement is declared"
        )

    def test_spdx3_empty_subject_with_rootelement_accepted(self) -> None:
        """Positive control: with a declared rootElement, an empty-subject
        annotation is treated as document-scoped."""
        sbom_data = self._build_spdx3_with_empty_subject_annotation(root_elements=["SPDXRef-Package-1"])

        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert all(f.status == "pass" for f in cle_findings), (
            "Empty-subject annotation should be accepted when rootElement is present"
        )

    def test_spdx3_package_scoped_annotation_does_not_pass_root(self) -> None:
        """A top-level Annotation whose subject is a non-root package does
        not feed the root's doc-level CLE fallback."""
        sbom_data = _create_base_spdx3_sbom()
        sbom_data["@graph"] = [e for e in sbom_data["@graph"] if e.get("type") != "Annotation"]
        for e in sbom_data["@graph"]:
            if e.get("type") == "software_Package":
                e.pop("software_validUntilDate", None)
        # Add an extra non-root package
        sbom_data["@graph"].append(
            {
                "type": "software_Package",
                "spdxId": "SPDXRef-Package-2",
                "name": "other-package",
                "software_packageVersion": "2.0.0",
                "originatedBy": ["SPDXRef-Supplier"],
                "externalIdentifiers": [{"externalIdentifierType": "packageURL", "identifier": "pkg:pypi/other@2.0.0"}],
            }
        )
        # Declare the document with Package-1 as the only root; an annotation
        # targeting Package-2 must not feed Package-1's fallback.
        sbom_data["@graph"].append(
            {
                "type": "SpdxDocument",
                "spdxId": "SPDXRef-Document",
                "rootElement": ["SPDXRef-Package-1"],
            }
        )
        sbom_data["@graph"].append(
            {
                "type": "Annotation",
                "spdxId": "SPDXRef-Annotation-Off",
                "subject": "SPDXRef-Package-2",
                "statement": "cle:supportStatus=active cle:endOfSupport=2027-12-31",
            }
        )

        result = self._assess_sbom(sbom_data)

        cle_findings = [f for f in result.findings if "cle:" in f.id]
        assert all(f.status == "fail" for f in cle_findings), (
            f"Package-scoped annotation must not grant root fallback: {[(f.id, f.status) for f in cle_findings]}"
        )

    def _assess_sbom(self, sbom_data: dict) -> AssessmentResult:
        """Helper to write SBOM to temp file and assess it."""
        plugin = FDAMedicalDevicePlugin()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test-sbom-id", Path(f.name))


class TestFileTypeComponentSkipped:
    """File-type components should be skipped in unique-identifier checks."""

    def _assess_sbom(self, sbom_data: dict) -> "AssessmentResult":
        plugin = FDAMedicalDevicePlugin()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sbom_data, f)
            f.flush()
            return plugin.assess("test-sbom-id", Path(f.name))

    def test_cyclonedx_file_type_skipped(self) -> None:
        """CycloneDX type=file should not fail unique-identifiers."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "django",
                    "version": "5.2.3",
                    "type": "library",
                    "publisher": "Django",
                    "purl": "pkg:pypi/django@5.2.3",
                    "properties": [
                        {"name": "cdx:lifecycle:milestone:endOfSupport", "value": "2027-12-31"},
                    ],
                },
                {
                    "name": "uv.lock",
                    "type": "file",
                },
            ],
            "dependencies": [{"ref": "pkg:pypi/django@5.2.3", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2026-01-01T00:00:00Z",
            },
        }
        result = self._assess_sbom(sbom_data)

        uid_finding = next((f for f in result.findings if f.id == "fda-2025:ntia:unique-identifiers"), None)
        assert uid_finding is not None
        assert uid_finding.status == "pass", f"type=file should be skipped: {uid_finding.description}"

    def test_spdx_file_entry_skipped(self) -> None:
        """SPDX -File- packages should not fail unique-identifiers."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "test",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/test",
            "creationInfo": {
                "created": "2026-01-01T00:00:00Z",
                "creators": ["Tool: test"],
            },
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-django",
                    "name": "django",
                    "versionInfo": "5.2.3",
                    "supplier": "Organization: Django",
                    "downloadLocation": "NOASSERTION",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/django@5.2.3",
                        }
                    ],
                },
                {
                    "SPDXID": "SPDXRef-DocumentRoot-File-uv.lock",
                    "name": "uv.lock",
                    "downloadLocation": "NOASSERTION",
                },
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Package-django",
                }
            ],
        }
        result = self._assess_sbom(sbom_data)

        uid_finding = next((f for f in result.findings if f.id == "fda-2025:ntia:unique-identifiers"), None)
        assert uid_finding is not None
        assert uid_finding.status == "pass", f"File entry should be skipped: {uid_finding.description}"

    def test_cyclonedx_file_type_skipped_in_supplier_version_and_cle(self) -> None:
        """FDA file-type skip must extend to supplier, version and CLE checks,
        not just unique-identifiers. A lockfile has no supplier/version/lifecycle
        by nature — it's input metadata, not a software component.
        """
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "django",
                    "version": "5.2.3",
                    "type": "library",
                    "publisher": "Django",
                    "purl": "pkg:pypi/django@5.2.3",
                    "properties": [
                        {"name": "cdx:lifecycle:milestone:endOfSupport", "value": "2027-12-31"},
                    ],
                },
                {
                    # Bare file-type entry — no supplier, version, or CLE fields
                    "name": "uv.lock",
                    "type": "file",
                },
            ],
            "dependencies": [{"ref": "pkg:pypi/django@5.2.3", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2026-01-01T00:00:00Z",
            },
        }
        result = self._assess_sbom(sbom_data)

        for finding_id in (
            "fda-2025:ntia:supplier-name",
            "fda-2025:ntia:version",
            "fda-2025:cle:support-status",
            "fda-2025:cle:end-of-support",
        ):
            finding = next((f for f in result.findings if f.id == finding_id), None)
            assert finding is not None, f"{finding_id} missing from findings"
            assert finding.status == "pass", (
                f"{finding_id} should pass (file-type entry skipped): {finding.description}"
            )

    def test_spdx_file_entry_skipped_in_supplier_version_and_cle(self) -> None:
        """SPDX File-entries must be skipped for supplier, version and CLE checks."""
        sbom_data = {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": "test",
            "dataLicense": "CC0-1.0",
            "documentNamespace": "https://example.com/test",
            "creationInfo": {
                "created": "2026-01-01T00:00:00Z",
                "creators": ["Tool: test"],
            },
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-django",
                    "name": "django",
                    "versionInfo": "5.2.3",
                    "supplier": "Organization: Django",
                    "downloadLocation": "NOASSERTION",
                    "validUntilDate": "2027-12-31T00:00:00Z",
                    "annotations": [
                        {
                            "annotationType": "OTHER",
                            "annotator": "Tool: sbomify",
                            "annotationDate": "2026-01-01T00:00:00Z",
                            "comment": "cle:supportStatus=active",
                        }
                    ],
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": "pkg:pypi/django@5.2.3",
                        }
                    ],
                },
                {
                    # Bare file entry — no supplier/versionInfo/validUntilDate
                    "SPDXID": "SPDXRef-DocumentRoot-File-uv.lock",
                    "name": "uv.lock",
                    "downloadLocation": "NOASSERTION",
                },
            ],
            "relationships": [
                {
                    "spdxElementId": "SPDXRef-DOCUMENT",
                    "relationshipType": "DESCRIBES",
                    "relatedSpdxElement": "SPDXRef-Package-django",
                }
            ],
        }
        result = self._assess_sbom(sbom_data)

        for finding_id in (
            "fda-2025:ntia:supplier-name",
            "fda-2025:ntia:version",
            "fda-2025:cle:support-status",
            "fda-2025:cle:end-of-support",
        ):
            finding = next((f for f in result.findings if f.id == finding_id), None)
            assert finding is not None, f"{finding_id} missing from findings"
            assert finding.status == "pass", f"{finding_id} should pass (File entry skipped): {finding.description}"

    def test_cyclonedx_library_still_fails_alongside_file_type(self) -> None:
        """Regression guard: real library without CLE data must still fail."""
        sbom_data = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "components": [
                {
                    "name": "broken-lib",
                    "version": "1.0.0",
                    "type": "library",
                    "publisher": "SomeOrg",
                    "purl": "pkg:pypi/broken-lib@1.0.0",
                    # No CLE properties
                },
                {"name": "uv.lock", "type": "file"},
            ],
            "dependencies": [{"ref": "pkg:pypi/broken-lib@1.0.0", "dependsOn": []}],
            "metadata": {
                "authors": [{"name": "Dev"}],
                "timestamp": "2026-01-01T00:00:00Z",
            },
        }
        result = self._assess_sbom(sbom_data)

        for finding_id in ("fda-2025:cle:support-status", "fda-2025:cle:end-of-support"):
            finding = next((f for f in result.findings if f.id == finding_id), None)
            assert finding is not None, f"{finding_id} missing"
            assert finding.status == "fail", (
                f"{finding_id} must fail for library without CLE data (got {finding.status})"
            )
            assert "broken-lib" in (finding.description or "")
            assert "uv.lock" not in (finding.description or ""), "file-type entry must not appear in CLE failure list"
