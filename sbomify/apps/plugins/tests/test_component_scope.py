"""Non-software components are exempt from the per-component software checks.

A CycloneDX ``device`` entry has no purl, carries a part revision rather than a
release in ``version``, and keeps its vendor in ``manufacturer`` — a field none
of the software minimum-element standards read. Grading it against NTIA, BSI,
CISA or FDA therefore only measured the vocabulary mismatch. These tests pin the
exemption, and pin that software components are still graded exactly as before.
"""

from collections.abc import Callable
from typing import Any

import pytest

from sbomify.apps.plugins.builtins._component_scope import is_non_software_component
from sbomify.apps.plugins.builtins.bsi import BSICompliancePlugin
from sbomify.apps.plugins.builtins.cisa import CISAMinimumElementsPlugin
from sbomify.apps.plugins.builtins.fda_medical_device_cybersecurity import FDAMedicalDevicePlugin
from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin
from sbomify.apps.plugins.sdk.results import Finding

# No supplier, no version, no identifier — the shape an HBOM generator emits for
# a physical part.
BARE_DEVICE: dict[str, Any] = {"type": "device", "name": "STM32F407VGT6", "bom-ref": "part-1"}
BARE_LIBRARY: dict[str, Any] = {"type": "library", "name": "left-pad", "bom-ref": "pkg-1"}

Validate = Callable[[dict[str, Any]], list[Finding]]


def _ntia(bom: dict[str, Any]) -> list[Finding]:
    return NTIAMinimumElementsPlugin()._validate_cyclonedx(bom)


def _bsi(bom: dict[str, Any]) -> list[Finding]:
    return BSICompliancePlugin()._validate_cyclonedx(bom, "1.6")


def _cisa(bom: dict[str, Any]) -> list[Finding]:
    return CISAMinimumElementsPlugin()._validate_cyclonedx(bom)


def _fda(bom: dict[str, Any]) -> list[Finding]:
    return FDAMedicalDevicePlugin()._validate_cyclonedx(bom)


# Per plugin: the findings derived from supplier, version and unique identifier,
# mapped to the status a software component missing all three has always earned.
PLUGIN_CASES: dict[str, tuple[Validate, dict[str, str]]] = {
    "ntia": (
        _ntia,
        {
            "ntia-2021:supplier-name": "fail",
            "ntia-2021:version": "fail",
            "ntia-2021:unique-identifiers": "fail",
        },
    ),
    "bsi": (
        _bsi,
        {
            "bsi-tr03183:component-creator": "fail",
            "bsi-tr03183:component-version": "fail",
            "bsi-tr03183:unique-identifiers": "warning",
        },
    ),
    "cisa": (
        _cisa,
        {
            "cisa-2025:software-producer": "fail",
            "cisa-2025:component-version": "fail",
            "cisa-2025:software-identifiers": "fail",
        },
    ),
    "fda": (
        _fda,
        {
            "fda-2025:ntia:supplier-name": "fail",
            "fda-2025:ntia:version": "fail",
            "fda-2025:ntia:unique-identifiers": "fail",
        },
    ),
}

IDENTITY_CASES = [pytest.param(validate, expected, id=name) for name, (validate, expected) in PLUGIN_CASES.items()]
VALIDATE_CASES = [pytest.param(validate, id=name) for name, (validate, _) in PLUGIN_CASES.items()]


def _bom(*components: dict[str, Any]) -> dict[str, Any]:
    """A CycloneDX BOM carrying `components` and nothing else of interest."""
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": list(components),
        "dependencies": [{"ref": c["bom-ref"], "dependsOn": []} for c in components],
        "metadata": {
            "timestamp": "2024-01-01T00:00:00Z",
            "authors": [{"name": "Test Author", "email": "author@example.com"}],
            "manufacturer": {"name": "Test Corp", "url": ["https://example.com"]},
        },
    }


def _statuses(findings: list[Finding], finding_ids: dict[str, str]) -> dict[str, str | None]:
    by_id = {f.id: f for f in findings}
    return {finding_id: by_id[finding_id].status for finding_id in finding_ids}


def _fingerprint(findings: list[Finding]) -> dict[str, tuple[str | None, str]]:
    """Status plus description per finding. The description names the offending
    components, so a component that leaked into a check shows up here."""
    return {f.id: (f.status, f.description) for f in findings}


class TestIsNonSoftwareComponent:
    def test_hardware_and_file_are_exempt(self) -> None:
        assert is_non_software_component({"type": "device"})
        assert is_non_software_component({"type": "file"})

    def test_type_match_is_case_insensitive(self) -> None:
        assert is_non_software_component({"type": "Device"})

    @pytest.mark.parametrize("component_type", ["firmware", "device-driver", "platform", "library", "application"])
    def test_software_types_are_still_graded(self, component_type: str) -> None:
        # Firmware, drivers and platforms sit in a hardware BOM next to the
        # device, but they are software releases: real vendor, real version.
        assert not is_non_software_component({"type": component_type})

    def test_missing_or_unknown_type_is_graded(self) -> None:
        assert not is_non_software_component({"name": "typeless"})
        assert not is_non_software_component({"type": "widget"})


@pytest.mark.parametrize(("validate", "expected"), IDENTITY_CASES)
def test_device_passes_the_identity_checks(validate: Validate, expected: dict[str, str]) -> None:
    findings = validate(_bom(BARE_DEVICE))

    assert _statuses(findings, expected) == dict.fromkeys(expected, "pass")


@pytest.mark.parametrize(("validate", "expected"), IDENTITY_CASES)
def test_software_component_is_graded_as_before(validate: Validate, expected: dict[str, str]) -> None:
    findings = validate(_bom(BARE_LIBRARY))

    assert _statuses(findings, expected) == expected


@pytest.mark.parametrize("validate", VALIDATE_CASES)
def test_device_does_not_move_the_score(validate: Validate) -> None:
    """Adding a bare device to a software BOM leaves every finding untouched —
    status and named components alike."""
    software_only = _fingerprint(validate(_bom(BARE_LIBRARY)))
    with_device = _fingerprint(validate(_bom(BARE_LIBRARY, BARE_DEVICE)))

    assert with_device == software_only


@pytest.mark.parametrize("validate", VALIDATE_CASES)
def test_nameless_device_still_fails_component_name(validate: Validate) -> None:
    """The exemption covers the software fields, not basic data quality."""
    findings = validate(_bom({"type": "device", "bom-ref": "part-1"}))
    name_findings = [f for f in findings if f.id.endswith("component-name")]

    assert name_findings
    assert all(f.status == "fail" for f in name_findings)
