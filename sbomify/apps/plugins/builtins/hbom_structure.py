"""HBOM structure assessment: CISA HBOM Framework field coverage and CycloneDX hardware conventions.

Runs on ``bom_type=hbom`` only and is gated on ``requires_hardware_components``,
so a software document never reaches it. The artifact is read and projected on
the fly (ADR-004); nothing here is written back.

Two checks, deliberately no more:

* **CISA HBOM Framework, Appendix C** — the only published HBOM field taxonomy
  (ICT SCRM Task Force, September 2023), and explicitly voluntary. CISA's own
  CycloneDX mapping annotates all but a handful of its ~40 fields "Equivalent
  CycloneDX field: None", so only the mappable fields are scored and the rest
  are reported once as an informational note. A document is never marked down
  for a field the format cannot express.
* **CycloneDX hardware conventions** — ``manufacturer`` / ``supplier`` on
  devices, the ``cdx:device`` namespace of the CycloneDX property taxonomy
  (quantity and board location are what make an HBOM readable as a parts list),
  and the 1.7 guidance that a device carrying firmware should be accompanied by
  a firmware component linked through the dependency graph.

Findings cite the CISA framework or the CycloneDX property taxonomy and nothing
else. The CISA framework is voluntary, so a field it asks for and CycloneDX
cannot express is reported once as a note and never scored, and a mappable
field it asks for warns rather than fails.

An HBOM *is* required by name in two US instruments — FY2026 NDAA §877 for
fifth-generation wireless on military installations, and EO 14415 §3(b)(i) for
DoW national-security acquisitions — but neither prescribes a format, so no
finding here may claim to measure compliance with either. The CRA, the FDA
premarket guidance and OpenChain require no HBOM at all; none of them may be
cited in a finding.

One thing does fail: a part naming neither a manufacturer nor a supplier. That
is a gap CycloneDX can express, it is the same standard NTIA and BSI hold
software to, and leaving it a warning let a document with unattributable parts
earn a public badge reading "All checks passed" — the run counts as passing
whenever anything passed at all.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sbomify.apps.plugins.builtins._crypto_assessment import summarize
from sbomify.apps.plugins.sdk import (
    AssessmentCategory,
    AssessmentPlugin,
    AssessmentResult,
    AssessmentSummary,
    Finding,
    PluginMetadata,
    ScanMode,
)
from sbomify.apps.plugins.sdk.base import SBOMContext
from sbomify.apps.sboms.hardware_inventory import HardwarePart, derive_hardware_inventory

_PLUGIN_NAME = "hbom-structure"

_CISA = "CISA's voluntary HBOM Framework (Appendix C, September 2023)"
_TAXONOMY = "the CycloneDX property taxonomy"
_TAXONOMY_URL = "https://github.com/CycloneDX/cyclonedx-property-taxonomy"

# Compliance findings key off status; severity is cosmetic. A voluntary
# recommendation that is not followed is a gap rather than a violation, so
# almost everything here warns; see the module docstring for the one exception.
# nosec B105 — "pass" here is the finding status, not a password. Bandit reads
# the key as a credential name once the dict has more than three entries.
_SEVERITY = {"pass": "info", "warning": "medium", "info": "info", "fail": "high"}  # nosec B105

# The software counterpart CycloneDX 1.7 expects alongside a device that runs code.
_PAIRED_SOFTWARE_TYPES = frozenset({"firmware", "operating-system"})

_FIRMWARE_NAME_RE = re.compile(r"\b(firmware|bootloader|bios|uefi|u-boot|microcode)\b", re.IGNORECASE)

# A real parts list runs to thousands of lines; the stored result names only the
# first few offenders and keeps the full count alongside them.
_MAX_LISTED = 25


def _text(value: Any) -> str | None:
    """A non-empty string, or None for anything else."""
    return value.strip() or None if isinstance(value, str) else None


def _components(document: dict[str, Any]) -> list[dict[str, Any]]:
    raw = document.get("components")
    return [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []


def _key(part: HardwarePart) -> str | None:
    """Identity of a part, preferring its bom-ref — matches ``_hashed_keys``."""
    return part.bom_ref or part.name


def _hashed_keys(components: list[dict[str, Any]]) -> set[str]:
    """Identities of the components carrying at least one hash."""
    keys = set()
    for component in components:
        hashes = component.get("hashes")
        if isinstance(hashes, list) and hashes:
            if key := _text(component.get("bom-ref")) or _text(component.get("name")):
                keys.add(key)
    return keys


def _has_maker(component: dict[str, Any]) -> bool:
    """True when a component names a manufacturer or, failing that, a supplier."""
    return any(
        isinstance(entity := component.get(field), dict) and bool(_text(entity.get("name")))
        for field in ("manufacturer", "supplier")
    )


def _has_author(metadata: dict[str, Any]) -> bool:
    authors = metadata.get("authors")
    if isinstance(authors, list) and any(isinstance(a, dict) and _text(a.get("name")) for a in authors):
        return True
    # metadata.author is deprecated in 1.6 but valid in every version we accept.
    return bool(_text(metadata.get("author")))


def _firmware_edges(
    document: dict[str, Any], device_refs: set[str], software_refs: set[str]
) -> tuple[set[str], set[str]]:
    """``(devices joined to firmware, firmware joined to a device)`` from the dependency graph.

    An edge counts in either direction. A document may declare the device as
    depending on the firmware it runs or the firmware as depending on the device
    it targets, and reading only one direction would warn about a relationship
    the document did record.
    """
    linked_devices: set[str] = set()
    linked_software: set[str] = set()
    dependencies = document.get("dependencies")
    if not isinstance(dependencies, list):
        return linked_devices, linked_software
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        ref = dependency.get("ref")
        depends_on = dependency.get("dependsOn")
        if not isinstance(ref, str) or not isinstance(depends_on, list):
            continue
        targets = {t for t in depends_on if isinstance(t, str)}
        if ref in device_refs and (hits := targets & software_refs):
            linked_devices.add(ref)
            linked_software |= hits
        if ref in software_refs and (hits := targets & device_refs):
            linked_software.add(ref)
            linked_devices |= hits
    return linked_devices, linked_software


def _finding(
    check: str,
    title: str,
    description: str,
    status: str,
    remediation: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Finding:
    return Finding(
        id=f"{_PLUGIN_NAME}:{check}",
        title=title,
        description=description,
        status=status,
        severity=_SEVERITY[status],
        # A failing check needs the way out as much as a warning does; only
        # pass/info drop the remediation, where there is nothing to fix.
        remediation=remediation if status in ("warning", "fail") else None,
        metadata=metadata,
    )


def _listed(names: list[str]) -> dict[str, Any] | None:
    if not names:
        return None
    return {"missing_count": len(names), "missing": names[:_MAX_LISTED]}


def _name(part: HardwarePart) -> str:
    return part.name or part.bom_ref or "(unnamed)"


def _unmapped_fields_note() -> Finding:
    return _finding(
        "cisa:unmapped-fields",
        "Most CISA HBOM fields have no CycloneDX equivalent",
        (
            f"{_CISA} defines roughly 40 fields across seven categories, and its own mapping annotates all but a "
            "handful of them 'Equivalent CycloneDX field: None'. Country of origin and the other location fields, "
            "quantity, lead time, technology node, and the supplier and part-code identifiers are among "
            "them. This check does not score those fields, and their absence is not a defect in this document: "
            f"CycloneDX 1.6 and 1.7 have nowhere to record them. Several travel in the `cdx:device` namespace of "
            f"{_TAXONOMY} by convention instead, which the property checks in this assessment cover."
        ),
        "info",
    )


class HbomStructurePlugin(AssessmentPlugin):
    """Score an HBOM against CISA's voluntary field taxonomy and CycloneDX hardware conventions."""

    VERSION = "1.0.0"
    STANDARD_NAME = "CISA Hardware Bill of Materials (HBOM) Framework"
    STANDARD_VERSION = "September 2023 (voluntary)"
    STANDARD_URL = (
        "https://www.cisa.gov/resources-tools/resources/"
        "hardware-bill-materials-hbom-framework-supply-chain-risk-management"
    )

    def get_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name=_PLUGIN_NAME,
            version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE,
            scan_mode=ScanMode.ONE_SHOT,
            supported_bom_types=["hbom"],
            requires_hardware_components=True,
        )

    def assess(
        self,
        sbom_id: str,
        sbom_path: Path,
        dependency_status: dict[str, Any] | None = None,
        context: SBOMContext | None = None,
    ) -> AssessmentResult:
        try:
            document = json.loads(sbom_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
            return self._error_result(f"Invalid JSON: {exc}")
        except OSError as exc:  # pragma: no cover - defensive
            return self._error_result(f"Failed to read SBOM: {exc}")

        if not isinstance(document, dict):
            return self._error_result("SBOM is not a JSON object")

        inventory = derive_hardware_inventory(document)
        if not inventory.parts:
            # The orchestrator dispatches an hbom-tagged artifact even when the
            # upload stamp says it holds no hardware. That combination is a
            # generator misfire or a mis-tagged upload, and stays visible.
            return self._result(
                [
                    _finding(
                        "no-hardware-components",
                        "No hardware components found",
                        (
                            "This artifact is tagged as a hardware BOM but declares no `device`, `firmware`, "
                            "`device-driver` or `platform` components, so there is no parts list to assess against "
                            f"{_CISA}. The generator may have misfired, or the document may describe software."
                        ),
                        "warning",
                        remediation="Confirm this is a hardware BOM and that its components carry hardware types.",
                    )
                ],
                device_count=0,
                hardware_component_count=0,
            )

        devices = [p for p in inventory.parts if p.type == "device"]
        components = _components(document)
        findings = self._cisa_findings(document, devices, components)
        findings.extend(self._convention_findings(document, devices, components))
        return self._result(findings, device_count=len(devices), hardware_component_count=inventory.count)

    def _cisa_findings(
        self, document: dict[str, Any], devices: list[HardwarePart], components: list[dict[str, Any]]
    ) -> list[Finding]:
        raw_metadata = document.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        findings = [
            self._field(
                "hbom_modify_date",
                "metadata.timestamp",
                bool(_text(metadata.get("timestamp"))),
                "Record when the HBOM was generated in metadata.timestamp.",
            ),
            self._field(
                "hbom_author",
                "metadata.authors",
                _has_author(metadata),
                "Name whoever produced the HBOM in metadata.authors (metadata.author before 1.6).",
            ),
        ]
        findings.extend(self._fga_findings(metadata))
        findings.extend(self._component_findings(devices, components))
        findings.append(_unmapped_fields_note())
        return findings

    def _field(self, field: str, path: str, present: bool, fix: str) -> Finding:
        """One mappable CISA field read off a single CycloneDX path."""
        state = "is present" if present else "is absent"
        return _finding(
            f"cisa:{field}",
            f"{field.upper()}: {path} {state}",
            f"{_CISA} maps its {field.upper()} field to CycloneDX `{path}`, which {state} in this document.",
            "pass" if present else "warning",
            remediation=fix,
        )

    def _fga_findings(self, metadata: dict[str, Any]) -> list[Finding]:
        """The four final-goods-assembly fields, all read off ``metadata.component``."""
        component = metadata.get("component")
        if not isinstance(component, dict):
            # One finding rather than four: the four FGA fields share a single
            # root cause when the assembly itself is missing.
            return [
                _finding(
                    "cisa:fga",
                    "Final goods assembly not identified",
                    (
                        "The document declares no metadata.component, so the assembly it describes is unnamed. "
                        f"{_CISA} maps its FGA_NUM, FGA_VERSION, FGA_HASH and FGA_MAIN_MANUFACTURER fields to that "
                        "component, and none of them can be read from this document."
                    ),
                    "warning",
                    remediation="Describe the assembled product in metadata.component with a name, version and maker.",
                )
            ]
        hashes = component.get("hashes")
        return [
            self._field(
                "fga_num",
                "metadata.component.name",
                bool(_text(component.get("name"))),
                "Name the assembly in metadata.component.name, using its assembly or part number.",
            ),
            self._field(
                "fga_version",
                "metadata.component.version",
                bool(_text(component.get("version"))),
                "Record the assembly revision in metadata.component.version.",
            ),
            self._field(
                "fga_hash",
                "metadata.component.hashes",
                isinstance(hashes, list) and bool(hashes),
                "Add a hash of the design or build artifact under metadata.component.hashes.",
            ),
            self._field(
                "fga_main_manufacturer",
                "metadata.component.manufacturer",
                _has_maker(component),
                "Identify who builds the assembly in metadata.component.manufacturer (or supplier before 1.6).",
            ),
        ]

    def _component_findings(self, devices: list[HardwarePart], components: list[dict[str, Any]]) -> list[Finding]:
        """The four mappable per-component CISA fields, aggregated over the parts list."""
        if not devices:
            return []
        hashed = _hashed_keys(components)
        return [
            self._coverage(
                "cisa:comp_manufacturer_pn",
                "COMP_MANUFACTURER_PN",
                "component.name",
                devices,
                [d for d in devices if not d.name],
                f"{_CISA} maps its COMP_MANUFACTURER_PN field to that CycloneDX field.",
                "Carry the manufacturer part number in component.name, as the CycloneDX hardware example does.",
            ),
            self._coverage(
                "cisa:comp_version",
                "COMP_VERSION",
                "component.version",
                devices,
                [d for d in devices if not d.revision],
                f"{_CISA} maps its COMP_VERSION field to that CycloneDX field.",
                "Record each part's revision in component.version.",
            ),
            self._coverage(
                "cisa:comp_hash",
                "COMP_HASH",
                "component.hashes",
                devices,
                [d for d in devices if _key(d) not in hashed],
                f"{_CISA} maps its COMP_HASH field to that CycloneDX field.",
                "Add component.hashes where a part has a hashable artifact, such as a programmed image.",
            ),
            self._manufacturer_finding(devices),
        ]

    def _manufacturer_finding(self, devices: list[HardwarePart]) -> Finding:
        """COMP_MANUFACTURER, plus who the CycloneDX field says the party actually is."""
        missing = [d for d in devices if not d.manufacturer]
        indirect = [d for d in devices if d.manufacturer and d.manufacturer_source != "manufacturer"]
        covered = len(devices) - len(missing)
        description = (
            f"{covered} of {len(devices)} device components identify a maker. {_CISA} maps its COMP_MANUFACTURER "
            "field to CycloneDX `component.manufacturer` (1.6 and later), and `component.supplier` carries the "
            "same party in earlier documents."
        )
        if indirect:
            description += (
                f" Of those, {len(indirect)} name only a supplier or publisher: whoever sold the part is not "
                "necessarily whoever made it, and the framework's field asks for the manufacturer."
            )
        metadata = _listed([_name(d) for d in missing]) or {}
        if indirect:
            metadata["supplier_only"] = [_name(d) for d in indirect][:_MAX_LISTED]
            metadata["supplier_only_count"] = len(indirect)
        return _finding(
            "cisa:comp_manufacturer",
            f"COMP_MANUFACTURER declared on {covered} of {len(devices)} devices",
            description,
            # The one failing check. manufacturer here already carries the
            # supplier and publisher fallbacks, so missing means the part names
            # nobody at all — unattributable hardware, which is the question an
            # HBOM exists to answer. Warning it let a document full of anonymous
            # parts earn a public "All checks passed" badge, since a run counts
            # as passing whenever anything in it passed.
            "fail" if missing else "pass",
            remediation="Identify who made each part in component.manufacturer, falling back to component.supplier.",
            metadata=metadata or None,
        )

    def _convention_findings(
        self, document: dict[str, Any], devices: list[HardwarePart], components: list[dict[str, Any]]
    ) -> list[Finding]:
        parts_list_citation = (
            f"It is a property in the `cdx:device` namespace of {_TAXONOMY}. A part number without a count and a "
            "board location cannot be read as a line on a parts list."
        )
        findings = [
            self._coverage(
                "cdx:quantity",
                "cdx:device:quantity",
                "cdx:device:quantity",
                devices,
                [d for d in devices if not d.quantity],
                parts_list_citation,
                "Add a cdx:device:quantity property giving how many of the part the assembly uses.",
            ),
            self._coverage(
                "cdx:location",
                "cdx:device:location",
                "cdx:device:location",
                devices,
                [d for d in devices if not d.location],
                parts_list_citation,
                "Add a cdx:device:location property giving where the part sits on the assembly.",
            ),
        ]
        findings.extend(self._firmware_findings(document, devices, components))
        return findings

    def _firmware_findings(
        self, document: dict[str, Any], devices: list[HardwarePart], components: list[dict[str, Any]]
    ) -> list[Finding]:
        firmware = [c for c in components if c.get("type") == "firmware"]
        software_refs = {
            ref
            for c in components
            if c.get("type") in _PAIRED_SOFTWARE_TYPES and (ref := _text(c.get("bom-ref"))) is not None
        }
        device_refs = {d.bom_ref for d in devices if d.bom_ref}
        linked_devices, linked_software = _firmware_edges(document, device_refs, software_refs)

        findings = []
        if firmware:
            orphans = [c for c in firmware if _text(c.get("bom-ref")) not in linked_software]
            covered = len(firmware) - len(orphans)
            findings.append(
                _finding(
                    "cdx:firmware-linkage",
                    f"{covered} of {len(firmware)} firmware components are linked to a device",
                    (
                        "CycloneDX 1.7 states that a device containing firmware should carry a separate firmware or "
                        "operating-system component alongside the hardware. The dependency graph records which "
                        "device runs which firmware; an unlinked firmware component leaves that unstated."
                    ),
                    "warning" if orphans else "pass",
                    remediation="Add a dependencies entry joining each device to the firmware it runs.",
                    metadata=_listed([_text(c.get("name")) or _text(c.get("bom-ref")) or "(unnamed)" for c in orphans]),
                )
            )

        # A firmware image declared as a device is the mirror image of the same
        # problem: the name is the only signal available, so this only ever warns.
        suspects = [
            d for d in devices if d.name and _FIRMWARE_NAME_RE.search(d.name) and d.bom_ref not in linked_devices
        ]
        if suspects:
            findings.append(
                _finding(
                    "cdx:device-named-like-firmware",
                    f"{len(suspects)} device components are named like firmware",
                    (
                        "These components are typed `device`, are named like firmware, and no firmware or "
                        "operating-system component links to them. CycloneDX 1.7 states that a device containing "
                        "firmware should carry both the physical hardware component and a separate firmware or "
                        "operating-system component."
                    ),
                    "warning",
                    remediation=(
                        "Declare firmware as a firmware component and join it to the device it runs on with a "
                        "dependency edge."
                    ),
                    metadata={"devices": [_name(d) for d in suspects][:_MAX_LISTED], "device_count": len(suspects)},
                )
            )
        return findings

    def _coverage(
        self,
        check: str,
        label: str,
        path: str,
        devices: list[HardwarePart],
        missing: list[HardwarePart],
        citation: str,
        fix: str,
    ) -> Finding:
        """One field scored across the parts list, named once with a coverage count."""
        covered = len(devices) - len(missing)
        return _finding(
            check,
            f"{label} declared on {covered} of {len(devices)} devices",
            f"{covered} of {len(devices)} device components declare `{path}`. {citation}",
            "warning" if missing else "pass",
            remediation=fix,
            metadata=_listed([_name(d) for d in missing]),
        )

    def _result(self, findings: list[Finding], device_count: int, hardware_component_count: int) -> AssessmentResult:
        return AssessmentResult(
            plugin_name=_PLUGIN_NAME,
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=summarize(findings),
            findings=findings,
            metadata={
                "standard_name": self.STANDARD_NAME,
                "standard_version": self.STANDARD_VERSION,
                "standard_url": self.STANDARD_URL,
                # Load-bearing: the framework is guidance, and a Trust Center
                # reader must not take these findings for a compliance verdict.
                "framework_is_voluntary": True,
                "taxonomy_url": _TAXONOMY_URL,
                "device_count": device_count,
                "hardware_component_count": hardware_component_count,
            },
        )

    def _error_result(self, message: str) -> AssessmentResult:
        return AssessmentResult(
            plugin_name=_PLUGIN_NAME,
            plugin_version=self.VERSION,
            category=AssessmentCategory.COMPLIANCE.value,
            assessed_at=datetime.now(timezone.utc).isoformat(),
            summary=AssessmentSummary(total_findings=1, error_count=1),
            findings=[
                Finding(
                    id=f"{_PLUGIN_NAME}:error",
                    title="HBOM structure assessment error",
                    description=message,
                    status="error",
                    severity="high",
                )
            ],
            metadata={"error": True},
        )
