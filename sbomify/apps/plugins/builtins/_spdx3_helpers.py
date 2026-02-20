"""Shared SPDX 3.0 extraction helpers for plugin SBOM analysis.

SPDX 3.0 uses a graph-based model with @context/@graph instead of the
flat document model of SPDX 2.x. This module provides common extraction
logic so plugins can handle both formats without duplicating graph-parsing.

Field mappings (SPDX 2.x → 3.0):
    packages[]              → @graph elements with type "software_Package"
    creationInfo.creators   → CreationInfo.createdBy → Person/Org externalIdentifiers
    creationInfo.created    → CreationInfo.created
    package.versionInfo     → software_packageVersion
    package.supplier        → originatedBy → Person/Org reference
    package.purl            → externalIdentifier with identifierType "packageURL"
    package.checksums       → verifiedUsing array (Hash elements)
    package.licenseConcluded→ Relationship hasConcludedLicense
    package.downloadLocation→ software_downloadLocation
    relationships           → @graph elements with type "Relationship"
"""

from typing import Any


def is_spdx3(sbom_data: dict[str, Any]) -> bool:
    """Check if SBOM is SPDX 3.0 format (has @context with spdx.org/rdf/3.0)."""
    context = sbom_data.get("@context", "")
    if isinstance(context, str):
        return "spdx.org/rdf/3.0" in context
    if isinstance(context, list):
        return any(isinstance(c, str) and "spdx.org/rdf/3.0" in c for c in context)
    return False


def extract_spdx3_elements(
    data: dict[str, Any],
) -> tuple[dict | None, list[dict], list[dict], dict[str, dict], dict[str, dict]]:
    """Extract typed elements from @graph.

    Args:
        data: Parsed SPDX 3.0 SBOM dictionary.

    Returns:
        Tuple of (creation_info, packages, relationships, persons_orgs, tools).
        persons_orgs and tools are keyed by spdxId.
    """
    elements = data.get("@graph", data.get("elements", []))

    creation_info: dict | None = None
    packages: list[dict] = []
    relationships: list[dict] = []
    persons_orgs: dict[str, dict] = {}
    tools: dict[str, dict] = {}

    for element in elements:
        elem_type = element.get("type", element.get("@type", ""))
        if "CreationInfo" in elem_type:
            creation_info = element
        elif "software_Package" in elem_type or elem_type == "Package":
            packages.append(element)
        elif "Relationship" in elem_type:
            relationships.append(element)
        elif "Person" in elem_type or "Organization" in elem_type:
            spdx_id = element.get("spdxId", element.get("@id", ""))
            if spdx_id:
                persons_orgs[spdx_id] = element
        elif "Tool" in elem_type or "SoftwareAgent" in elem_type:
            spdx_id = element.get("spdxId", element.get("@id", ""))
            if spdx_id:
                tools[spdx_id] = element

    return creation_info, packages, relationships, persons_orgs, tools


def get_spdx3_creation_info_fields(
    creation_info: dict | None,
    persons_orgs: dict[str, dict],
    tools: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """Extract creation info fields from SPDX 3.0 CreationInfo element.

    Args:
        creation_info: CreationInfo element dict (or None).
        persons_orgs: Mapping of spdxId → Person/Organization elements.
        tools: Mapping of spdxId → Tool/SoftwareAgent elements.

    Returns:
        Dict with keys: creators (list[str]), tool_entries (list[str]),
        timestamp (str|None).
    """
    if not creation_info:
        return {"creators": [], "tool_entries": [], "timestamp": None}

    tools = tools or {}

    # Extract creators from createdBy references
    creators: list[str] = []
    for ref in creation_info.get("createdBy", []):
        entity = persons_orgs.get(ref, {})
        name = entity.get("name", "")
        if name:
            creators.append(name)
        # Also check externalIdentifiers for email/URL
        for ext_id in entity.get("externalIdentifiers", []):
            identifier = ext_id.get("identifier", "")
            if identifier:
                creators.append(identifier)

    # Extract tool names from createdUsing references
    tool_entries: list[str] = []
    refs = creation_info.get("createdUsing", [])
    if isinstance(refs, list):
        for ref in refs:
            if isinstance(ref, str):
                tool_element = tools.get(ref)
                if tool_element:
                    tool_name = tool_element.get("name", "")
                    if tool_name:
                        tool_entries.append(tool_name)
                        continue
                tool_entries.append(ref)
            elif isinstance(ref, dict):
                tool_name = ref.get("name", "")
                if tool_name:
                    tool_entries.append(tool_name)

    timestamp = creation_info.get("created")

    return {
        "creators": creators,
        "tool_entries": tool_entries,
        "timestamp": timestamp,
    }


def get_spdx3_package_fields(
    package: dict[str, Any],
) -> dict[str, Any]:
    """Extract common fields from an SPDX 3.0 software_Package element.

    Args:
        package: A software_Package element dict.

    Returns:
        Dict with keys: name, version, supplier_refs, has_unique_id,
        has_hash, download_location, external_refs, external_identifiers.
    """
    name = package.get("name", "")
    version = package.get("software_packageVersion", "")
    supplier_refs = package.get("originatedBy", [])
    download_location = package.get("software_downloadLocation", "")

    # Check for unique identifiers (purl, cpe, swid)
    has_unique_id = False
    external_identifiers = package.get("externalIdentifiers", [])
    id_types = {"packageURL", "cpe22", "cpe23", "swid"}
    for ext_id in external_identifiers:
        if ext_id.get("externalIdentifierType", "") in id_types:
            has_unique_id = True
            break

    # Check for hash values in verifiedUsing
    has_hash = bool(package.get("verifiedUsing"))

    # External refs (for VCS, etc.)
    external_refs = package.get("externalRef", [])

    return {
        "name": name,
        "version": version,
        "supplier_refs": supplier_refs,
        "has_unique_id": has_unique_id,
        "has_hash": has_hash,
        "download_location": download_location,
        "external_refs": external_refs,
        "external_identifiers": external_identifiers,
    }
