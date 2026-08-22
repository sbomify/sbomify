"""Tests for the HBOM structure assessment plugin."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sbomify.apps.plugins.builtins.hbom_structure import HbomStructurePlugin
from sbomify.apps.plugins.sdk import AssessmentCategory

_HBOM_EXAMPLE = Path(__file__).parents[2] / "sboms" / "tests" / "test_data" / "hbom_pcie_sata_adapter.cdx.json"

# Nothing in the CRA, the FDA guidance or the OpenChain drafts requires an HBOM.
# Naming any of them in a customer-facing finding would misrepresent a voluntary
# framework as a legal obligation.
_FORBIDDEN_RE = re.compile(r"\b(CRA|Cyber Resilience Act|FDA|OpenChain|NDAA|EO 1\d{4})\b")


def _device(name: str, **fields: Any) -> dict[str, Any]:
    return {"type": "device", "bom-ref": name, "name": name, **fields}


def _document(*components: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1, "components": list(components), **extra}


def _assess(document: dict[str, Any], tmp_path: Path):
    path = tmp_path / "hbom.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return HbomStructurePlugin().assess("test-sbom-id", path)


def _by_id(result, check: str):
    return next(f for f in result.findings if f.id == f"hbom-structure:{check}")


def _ids(result) -> set[str]:
    return {f.id for f in result.findings}


def test_metadata_is_hbom_only_and_hardware_gated():
    metadata = HbomStructurePlugin().get_metadata()

    assert metadata.name == "hbom-structure"
    assert metadata.category is AssessmentCategory.COMPLIANCE
    # hbom only: an ordinary SBOM must never be scored against a hardware taxonomy.
    assert metadata.supported_bom_types == ["hbom"]
    assert metadata.requires_hardware_components is True


def test_pcie_sata_example_scores_well_and_flags_what_it_omits(tmp_path: Path):
    result = _assess(json.loads(_HBOM_EXAMPLE.read_text()), tmp_path)

    assert result.plugin_name == "hbom-structure"
    assert result.metadata["device_count"] == 6
    assert result.metadata["framework_is_voluntary"] is True

    # Present: timestamp, the assembly and its version, part numbers, suppliers,
    # and a quantity plus a board location on every one of the six parts.
    for check in (
        "cisa:hbom_modify_date",
        "cisa:fga_num",
        "cisa:fga_version",
        "cisa:comp_manufacturer_pn",
        "cisa:comp_manufacturer",
        "cdx:quantity",
        "cdx:location",
    ):
        assert _by_id(result, check).status == "pass", check

    # Genuinely absent: no author, no assembly hash or maker, one version in six,
    # no component hashes.
    for check in ("cisa:hbom_author", "cisa:fga_hash", "cisa:fga_main_manufacturer", "cisa:comp_hash"):
        assert _by_id(result, check).status == "warning", check
    version = _by_id(result, "cisa:comp_version")
    assert version.status == "warning"
    assert version.metadata["missing_count"] == 5

    # The 1.4 example identifies suppliers, not manufacturers — a pass, with the
    # distinction stated rather than glossed over.
    manufacturer = _by_id(result, "cisa:comp_manufacturer")
    assert manufacturer.metadata["supplier_only_count"] == 6
    assert "supplier" in manufacturer.description

    # No firmware in this document, so neither firmware check has anything to say.
    assert "hbom-structure:cdx:firmware-linkage" not in _ids(result)
    assert "hbom-structure:cdx:device-named-like-firmware" not in _ids(result)


def test_nothing_ever_fails_and_every_finding_cites_a_named_source(tmp_path: Path):
    result = _assess(json.loads(_HBOM_EXAMPLE.read_text()), tmp_path)

    assert result.summary.fail_count == 0
    assert result.summary.error_count == 0
    for finding in result.findings:
        text = f"{finding.title} {finding.description}"
        assert "CISA" in text or "CycloneDX" in text, finding.id
        assert not _FORBIDDEN_RE.search(text), finding.id


def test_unmappable_fields_are_one_informational_note(tmp_path: Path):
    result = _assess(_document(_device("R1")), tmp_path)

    note = _by_id(result, "cisa:unmapped-fields")
    assert note.status == "info"
    assert [f for f in result.findings if f.id == note.id] == [note]
    assert "lead time" in note.description and "technology node" in note.description
    # The point of the note: absence of an unmappable field is not a defect.
    assert "not a defect" in note.description


def test_hbom_declaring_no_hardware_warns(tmp_path: Path):
    # The orchestrator dispatches an hbom-tagged artifact even when the upload
    # stamp says it holds no hardware; the misfire must stay visible.
    result = _assess(_document({"type": "library", "name": "requests", "version": "2.32.3"}), tmp_path)

    assert _ids(result) == {"hbom-structure:no-hardware-components"}
    assert result.findings[0].status == "warning"
    assert result.metadata["hardware_component_count"] == 0


def test_missing_assembly_is_one_finding_not_four(tmp_path: Path):
    result = _assess(_document(_device("R1")), tmp_path)

    assert _by_id(result, "cisa:fga").status == "warning"
    for check in ("cisa:fga_num", "cisa:fga_version", "cisa:fga_hash", "cisa:fga_main_manufacturer"):
        assert f"hbom-structure:{check}" not in _ids(result)


def test_missing_quantity_and_location_warn_with_the_offending_parts(tmp_path: Path):
    result = _assess(
        _document(
            _device("R1", properties=[{"name": "cdx:device:quantity", "value": "2"}]),
            _device("R2"),
        ),
        tmp_path,
    )

    quantity = _by_id(result, "cdx:quantity")
    assert quantity.status == "warning"
    assert quantity.metadata["missing"] == ["R2"]
    assert "cdx:device" in quantity.description
    location = _by_id(result, "cdx:location")
    assert location.status == "warning"
    assert location.metadata["missing_count"] == 2


def test_hashes_and_makers_are_read_from_the_document(tmp_path: Path):
    result = _assess(
        _document(
            _device(
                "R1",
                version="rev-2",
                hashes=[{"alg": "SHA-256", "content": "a" * 64}],
                manufacturer={"name": "Acme"},
                properties=[
                    {"name": "cdx:device:quantity", "value": "2"},
                    {"name": "cdx:device:location", "value": "mainboard"},
                ],
            ),
            metadata={
                "timestamp": "2026-07-30T00:00:00Z",
                "authors": [{"name": "Jane Doe"}],
                "component": {
                    "type": "device",
                    "name": "board-1",
                    "version": "rev-1",
                    "hashes": [{"alg": "SHA-256", "content": "b" * 64}],
                    "manufacturer": {"name": "Acme"},
                },
            },
        ),
        tmp_path,
    )

    assert result.summary.warning_count == 0
    assert _by_id(result, "cisa:comp_hash").status == "pass"
    assert _by_id(result, "cisa:comp_manufacturer").metadata is None  # no supplier-only caveat
    assert _by_id(result, "cisa:hbom_author").status == "pass"


def test_deprecated_singular_author_still_counts(tmp_path: Path):
    result = _assess(_document(_device("R1"), metadata={"author": "Jane Doe"}), tmp_path)

    assert _by_id(result, "cisa:hbom_author").status == "pass"


def test_unlinked_firmware_warns(tmp_path: Path):
    result = _assess(
        _document(_device("mcu"), {"type": "firmware", "bom-ref": "fw", "name": "mcu-fw", "version": "1.2"}),
        tmp_path,
    )

    linkage = _by_id(result, "cdx:firmware-linkage")
    assert linkage.status == "warning"
    assert linkage.metadata["missing"] == ["mcu-fw"]


def test_firmware_linked_in_either_direction_passes(tmp_path: Path):
    firmware = {"type": "firmware", "bom-ref": "fw", "name": "mcu-fw"}
    device_to_firmware = _document(_device("mcu"), firmware, dependencies=[{"ref": "mcu", "dependsOn": ["fw"]}])
    # Some generators express the same relationship the other way round; reading
    # only one direction would warn about a link the document did record.
    firmware_to_device = _document(_device("mcu"), firmware, dependencies=[{"ref": "fw", "dependsOn": ["mcu"]}])

    assert _by_id(_assess(device_to_firmware, tmp_path), "cdx:firmware-linkage").status == "pass"
    assert _by_id(_assess(firmware_to_device, tmp_path), "cdx:firmware-linkage").status == "pass"


def test_device_named_like_firmware_without_a_pair_warns(tmp_path: Path):
    result = _assess(_document(_device("boot-firmware-v2"), _device("R1")), tmp_path)

    suspect = _by_id(result, "cdx:device-named-like-firmware")
    assert suspect.status == "warning"
    assert suspect.metadata["devices"] == ["boot-firmware-v2"]


def test_device_named_like_firmware_with_a_pair_is_quiet(tmp_path: Path):
    result = _assess(
        _document(
            _device("boot-firmware-v2"),
            {"type": "firmware", "bom-ref": "fw", "name": "boot"},
            dependencies=[{"ref": "boot-firmware-v2", "dependsOn": ["fw"]}],
        ),
        tmp_path,
    )

    assert "hbom-structure:cdx:device-named-like-firmware" not in _ids(result)


def test_hostile_input_degrades_instead_of_raising(tmp_path: Path):
    result = _assess(
        _document(
            _device("R1", properties={"not": "a list"}, hashes="nope", manufacturer="Acme"),
            metadata={"timestamp": 17, "authors": "nobody", "component": ["not", "a", "dict"]},
            dependencies=[{"ref": None}, "junk"],
        ),
        tmp_path,
    )

    assert result.summary.error_count == 0
    assert _by_id(result, "cisa:hbom_modify_date").status == "warning"
    assert _by_id(result, "cisa:fga").status == "warning"


def test_invalid_json_reports_an_error(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    result = HbomStructurePlugin().assess("test-sbom-id", path)

    assert result.summary.error_count == 1
    assert result.metadata["error"] is True


def test_a_part_naming_nobody_fails(tmp_path: Path) -> None:
    """The one failing check.

    A run counts as passing whenever anything in it passed, so a warning here
    let a document of unattributable parts earn a public "All checks passed"
    badge. Naming neither a manufacturer nor a supplier is a gap CycloneDX can
    express, and it is the question an HBOM exists to answer.
    """
    result = _assess(_document(_device("R1")), tmp_path)

    assert _by_id(result, "cisa:comp_manufacturer").status == "fail"


def test_a_supplier_is_enough_to_pass(tmp_path: Path) -> None:
    """CycloneDX records a hardware vendor in manufacturer, but the reference
    example uses supplier, and either answers the question."""
    result = _assess(_document(_device("R1", supplier={"name": "Samtec"})), tmp_path)

    assert _by_id(result, "cisa:comp_manufacturer").status == "pass"


def test_the_reference_example_does_not_fail(tmp_path: Path) -> None:
    """Every device in the upstream CycloneDX PCIe-SATA example names a supplier,
    so the acceptance criterion that it scores well has to survive the fail."""
    result = _assess(json.loads(_HBOM_EXAMPLE.read_text()), tmp_path)

    assert [f.id for f in result.findings if f.status == "fail"] == []
