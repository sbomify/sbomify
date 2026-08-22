"""What the four software compliance plugins grade, per component type.

A CycloneDX ``device`` entry has no purl and carries a part revision rather
than a release in ``version``, so grading it on identifiers or version only
measures the vocabulary mismatch. It does name its vendor, in ``manufacturer``
— all four plugins read that field, so a device is graded on supplier like
anything else. A ``file`` entry is the generator's own scan input and is
exempt from every per-component field.

An element that graded nothing — every component exempt from it — reports
``warning`` rather than a pass it never earned. A document with no components
at all is untouched: that is a different defect.

These tests pin the split, and pin that software components are still graded
exactly as before.
"""

from collections.abc import Callable
from typing import Any

import pytest

from sbomify.apps.plugins.builtins._component_scope import (
    element_verdict,
    get_component_supplier,
    is_non_software_component,
    is_supplier_exempt,
    nothing_to_grade,
)
from sbomify.apps.plugins.builtins.bsi import BSICompliancePlugin
from sbomify.apps.plugins.builtins.cisa import CISAMinimumElementsPlugin
from sbomify.apps.plugins.builtins.fda_medical_device_cybersecurity import FDAMedicalDevicePlugin
from sbomify.apps.plugins.builtins.ntia import NTIAMinimumElementsPlugin
from sbomify.apps.plugins.sdk.results import Finding

# No supplier, no version, no identifier — the shape an HBOM generator emits
# for a physical part it knows nothing about.
BARE_DEVICE: dict[str, Any] = {"type": "device", "name": "STM32F407VGT6", "bom-ref": "part-1"}
# The same part with its vendor named. BSI asks the creator for contact
# details rather than a name, so a populated manufacturer carries both.
VENDOR_DEVICE: dict[str, Any] = {
    **BARE_DEVICE,
    "manufacturer": {"name": "STMicroelectronics", "url": ["https://www.st.com"]},
}
BARE_FILE: dict[str, Any] = {"type": "file", "name": "uv.lock", "bom-ref": "file-1"}
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


# Per plugin: the supplier finding (BSI calls it the component creator), then
# the version and unique-identifier findings a device is exempt from, mapped to
# the status a software component missing all three has always earned. BSI's
# identifier element is advisory rather than mandatory, hence its warning.
PLUGIN_CASES: dict[str, tuple[Validate, str, dict[str, str]]] = {
    "ntia": (
        _ntia,
        "ntia-2021:supplier-name",
        {"ntia-2021:version": "fail", "ntia-2021:unique-identifiers": "fail"},
    ),
    "bsi": (
        _bsi,
        "bsi-tr03183:component-creator",
        {"bsi-tr03183:component-version": "fail", "bsi-tr03183:unique-identifiers": "warning"},
    ),
    "cisa": (
        _cisa,
        "cisa-2025:software-producer",
        {"cisa-2025:component-version": "fail", "cisa-2025:software-identifiers": "fail"},
    ),
    "fda": (
        _fda,
        "fda-2025:ntia:supplier-name",
        {"fda-2025:ntia:version": "fail", "fda-2025:ntia:unique-identifiers": "fail"},
    ),
}

CASES = [pytest.param(*case, id=name) for name, case in PLUGIN_CASES.items()]
SUPPLIER_CASES = [pytest.param(validate, supplier, id=name) for name, (validate, supplier, _) in PLUGIN_CASES.items()]
VALIDATE_CASES = [pytest.param(validate, id=name) for name, (validate, _, __) in PLUGIN_CASES.items()]


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


def _status(findings: list[Finding], finding_id: str) -> str | None:
    return next(f.status for f in findings if f.id == finding_id)


def _statuses(findings: list[Finding], finding_ids: dict[str, str]) -> dict[str, str | None]:
    by_id = {f.id: f for f in findings}
    return {finding_id: by_id[finding_id].status for finding_id in finding_ids}


def _fingerprint(findings: list[Finding]) -> dict[str, tuple[str | None, str]]:
    """Status plus description per finding. The description names the offending
    components, so a component that leaked into a check shows up here."""
    return {f.id: (f.status, f.description) for f in findings}


class TestComponentPredicates:
    def test_hardware_and_file_are_non_software(self) -> None:
        assert is_non_software_component({"type": "device"})
        assert is_non_software_component({"type": "file"})

    def test_only_file_is_exempt_from_supplier(self) -> None:
        # A device names its vendor in manufacturer; a scan input has no vendor.
        assert is_supplier_exempt({"type": "file"})
        assert not is_supplier_exempt({"type": "device"})

    def test_type_match_is_case_insensitive(self) -> None:
        assert is_non_software_component({"type": "Device"})
        assert is_supplier_exempt({"type": "FILE"})

    @pytest.mark.parametrize("component_type", ["firmware", "device-driver", "platform", "library", "application"])
    def test_software_types_are_still_graded(self, component_type: str) -> None:
        # Firmware, drivers and platforms sit in a hardware BOM next to the
        # device, but they are software releases: real vendor, real version.
        assert not is_non_software_component({"type": component_type})

    def test_missing_or_unknown_type_is_graded(self) -> None:
        assert not is_non_software_component({"name": "typeless"})
        assert not is_non_software_component({"type": "widget"})
        assert not is_supplier_exempt({"type": "widget"})


class TestGetComponentSupplier:
    def test_reads_each_source(self) -> None:
        assert get_component_supplier({"publisher": "Django"}) == "Django"
        assert get_component_supplier({"supplier": {"name": "Acme"}}) == "Acme"
        assert get_component_supplier({"manufacturer": {"name": "STMicroelectronics"}}) == "STMicroelectronics"

    def test_publisher_wins_over_the_entities(self) -> None:
        component = {"publisher": "Django", "supplier": {"name": "Acme"}, "manufacturer": {"name": "STM"}}
        assert get_component_supplier(component) == "Django"

    def test_absent_and_malformed_fields_name_nobody(self) -> None:
        assert get_component_supplier({"name": "left-pad"}) is None
        assert get_component_supplier({"publisher": ""}) is None
        assert get_component_supplier({"publisher": ["Django"]}) is None
        assert get_component_supplier({"manufacturer": "STM"}) is None
        assert get_component_supplier({"manufacturer": {"url": ["https://st.com"]}}) is None


class TestElementVerdict:
    def test_failures_outrank_an_ungraded_document(self) -> None:
        assert element_verdict(["left-pad"], True) == ("fail", "Missing for: left-pad")

    def test_ungraded_document_warns(self) -> None:
        status, details = element_verdict([], True)
        assert status == "warning"
        assert details

    def test_clean_grading_run_passes(self) -> None:
        assert element_verdict([], False) == ("pass", None)

    def test_empty_document_is_not_ungraded(self) -> None:
        # No components at all is its own defect, graded elsewhere.
        assert not nothing_to_grade([])
        assert nothing_to_grade([BARE_DEVICE, BARE_FILE])
        assert not nothing_to_grade([BARE_DEVICE, BARE_LIBRARY])
        # Supplier keeps grading the device, so its exemption does not apply.
        assert not nothing_to_grade([BARE_DEVICE], is_supplier_exempt)
        assert nothing_to_grade([BARE_FILE], is_supplier_exempt)


@pytest.mark.parametrize(("validate", "supplier_id"), SUPPLIER_CASES)
def test_device_naming_a_manufacturer_passes_supplier(validate: Validate, supplier_id: str) -> None:
    assert _status(validate(_bom(VENDOR_DEVICE)), supplier_id) == "pass"


@pytest.mark.parametrize(("validate", "supplier_id"), SUPPLIER_CASES)
def test_device_naming_nobody_fails_supplier(validate: Validate, supplier_id: str) -> None:
    assert _status(validate(_bom(BARE_DEVICE)), supplier_id) == "fail"


@pytest.mark.parametrize(("validate", "supplier_id"), SUPPLIER_CASES)
def test_manufacturer_is_a_supplier_source_for_software_too(validate: Validate, supplier_id: str) -> None:
    """The scoring change this brings to existing software SBOMs: a component
    that names its vendor only in manufacturer now passes."""
    library = {**BARE_LIBRARY, "manufacturer": {"name": "Acme", "url": ["https://acme.example"]}}

    assert _status(validate(_bom(library)), supplier_id) == "pass"


@pytest.mark.parametrize(("validate", "supplier_id", "expected"), CASES)
def test_device_is_exempt_from_version_and_identifiers(
    validate: Validate, supplier_id: str, expected: dict[str, str]
) -> None:
    """A device that names nobody is still graded on supplier, and still not
    on the two elements that describe a software release."""
    library_only = _fingerprint(validate(_bom(BARE_LIBRARY)))
    findings = validate(_bom(BARE_LIBRARY, BARE_DEVICE))

    for element in expected:
        assert _fingerprint(findings)[element] == library_only[element]
    assert "STM32F407VGT6" in next(f.description for f in findings if f.id == supplier_id)


@pytest.mark.parametrize(("validate", "_supplier_id", "expected"), CASES)
def test_software_component_is_graded_as_before(
    validate: Validate, _supplier_id: str, expected: dict[str, str]
) -> None:
    findings = validate(_bom(BARE_LIBRARY))

    assert _statuses(findings, expected) == expected


@pytest.mark.parametrize("validate", VALIDATE_CASES)
def test_vendor_device_does_not_move_the_score(validate: Validate) -> None:
    """Adding a device that names its vendor to a software BOM leaves every
    finding untouched — status and named components alike."""
    software_only = _fingerprint(validate(_bom(BARE_LIBRARY)))
    with_device = _fingerprint(validate(_bom(BARE_LIBRARY, VENDOR_DEVICE)))

    assert with_device == software_only


@pytest.mark.parametrize("validate", VALIDATE_CASES)
def test_nameless_device_still_fails_component_name(validate: Validate) -> None:
    """The exemption covers the software fields, not basic data quality."""
    findings = validate(_bom({"type": "device", "bom-ref": "part-1"}))
    name_findings = [f for f in findings if f.id.endswith("component-name")]

    assert name_findings
    assert all(f.status == "fail" for f in name_findings)


@pytest.mark.parametrize(("validate", "supplier_id", "expected"), CASES)
def test_all_device_document_warns_instead_of_passing(
    validate: Validate, supplier_id: str, expected: dict[str, str]
) -> None:
    """Every component exempt means the check graded nothing, and an empty
    failure list is not a pass. Supplier still reports a real verdict."""
    findings = validate(_bom(VENDOR_DEVICE, {**BARE_DEVICE, "name": "MCP4725", "bom-ref": "part-2"}))

    assert _statuses(findings, expected) == dict.fromkeys(expected, "warning")
    assert _status(findings, supplier_id) == "fail"  # the second device names nobody


@pytest.mark.parametrize(("validate", "supplier_id", "expected"), CASES)
def test_all_file_document_warns_on_supplier_too(
    validate: Validate, supplier_id: str, expected: dict[str, str]
) -> None:
    findings = validate(_bom(BARE_FILE, {**BARE_FILE, "name": "poetry.lock", "bom-ref": "file-2"}))

    assert _statuses(findings, expected) == dict.fromkeys(expected, "warning")
    assert _status(findings, supplier_id) == "warning"


@pytest.mark.parametrize(("validate", "supplier_id", "expected"), CASES)
def test_document_without_components_is_unchanged(
    validate: Validate, supplier_id: str, expected: dict[str, str]
) -> None:
    """No components at all is a different defect, and not this rule's to
    redefine — those elements score exactly what they scored before."""
    findings = validate(_bom())

    assert "warning" not in _statuses(findings, expected).values()
    assert _status(findings, supplier_id) != "warning"


@pytest.mark.parametrize(("validate", "supplier_id", "expected"), CASES)
def test_one_library_among_devices_is_still_graded(
    validate: Validate, supplier_id: str, expected: dict[str, str]
) -> None:
    findings = validate(_bom(BARE_LIBRARY, VENDOR_DEVICE))

    assert _statuses(findings, expected) == expected
    assert _status(findings, supplier_id) == "fail"
    assert "left-pad" in next(f.description for f in findings if f.id == supplier_id)
