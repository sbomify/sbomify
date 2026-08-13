"""Shared SPDX 3.0 extraction helpers for plugin SBOM analysis.

SPDX 3.0 uses a graph-based model with @context/@graph instead of the
flat document model of SPDX 2.x. This module provides common extraction
logic so plugins can handle both formats without duplicating graph-parsing.

Field mappings (SPDX 2.x → 3.0.1):
    packages[]              → @graph elements with type "software_Package"
    creationInfo.creators   → CreationInfo.createdBy → Agent externalIdentifier
    creationInfo.created    → CreationInfo.created
    package.versionInfo     → software_packageVersion
    package.supplier        → originatedBy → Agent reference or inline object
    package.purl            → software_packageUrl, or externalIdentifier with
                              identifierType "packageUrl"
    package.checksums       → verifiedUsing array (Hash elements)
    package.licenseConcluded→ Relationship hasConcludedLicense
    package.downloadLocation→ software_downloadLocation
    relationships           → @graph elements with type "Relationship"

Reading rules that keep old documents scoring:
    - ``externalIdentifier`` is the spec property; ``externalIdentifiers`` is a
      non-spec spelling this codebase both wrote into fixtures and accepted
      from producers, so stored artifacts carry it. Both are read everywhere.
    - ``packageUrl`` is the vocabulary value; ``packageURL`` and ``purl`` are
      accepted variants for the same reason.
    - Anything in Agent position (createdBy, originatedBy, suppliedBy) may be
      a string reference, the literal "SpdxOrganization", or an inline Agent
      object — Agent_derived allows all three.
"""

from typing import Any

# The literal "SpdxOrganization" in an Agent position denotes the SPDX
# organisation itself, with no element in the graph to resolve.
_SPDX_ORGANIZATION_AGENT = {"type": "Organization", "name": "SPDX"}

# Every concrete Agent subtype plus the base type. Exact matches on the
# unprefixed tail — substring tests would put "SoftwareAgent" wherever
# "Agent" matches.
_AGENT_TYPES = frozenset({"Person", "Organization", "SoftwareAgent", "Agent"})

_UNIQUE_ID_TYPES = frozenset({"packageUrl", "packageURL", "purl", "cpe22", "cpe23", "swid", "gitoid", "swhid"})
_PURL_ID_TYPES = frozenset({"packageUrl", "packageURL", "purl"})


def is_spdx3(sbom_data: dict[str, Any]) -> bool:
    """Check if SBOM is SPDX 3.x format — the one detector every caller shares.

    Three signals, any of which decides it:
      - @context containing "spdx.org/rdf/3." (any 3.x line, so a 3.1
        document reaches the code that can reject it by name);
      - a root-level @graph, the JSON-LD element array no other supported
        format carries;
      - a legacy root spdxVersion starting with "SPDX-3.".
    """
    if not isinstance(sbom_data, dict):
        return False

    context = sbom_data.get("@context", "")
    if isinstance(context, str):
        if "spdx.org/rdf/3." in context:
            return True
    elif isinstance(context, list):
        for entry in context:
            if "spdx.org/rdf/3." in str(entry):
                return True
    elif isinstance(context, dict):
        if "spdx.org/rdf/3." in str(context):
            return True

    if isinstance(sbom_data.get("@graph"), list):
        return True

    spdx_version = sbom_data.get("spdxVersion") or ""
    if isinstance(spdx_version, str) and spdx_version.startswith("SPDX-3."):
        return True

    return False


def resolve_spdx3_agent(ref: Any, agents: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Resolve anything legal in an Agent position to an agent dict.

    Agent_derived allows an inline Agent object, the literal string
    "SpdxOrganization", or a reference into the graph. The inline form used
    to reach ``dict.get`` as a key and raise ``TypeError: unhashable type``,
    which failed the whole assessment run.
    """
    if isinstance(ref, dict):
        return ref
    if ref == "SpdxOrganization":
        return dict(_SPDX_ORGANIZATION_AGENT)
    if isinstance(ref, str):
        return agents.get(ref, {})
    return {}


def iter_spdx3_external_identifiers(entity: dict[str, Any]) -> list[dict[str, Any]]:
    """All ExternalIdentifier dicts on an element, spec and legacy spellings."""
    identifiers: list[dict[str, Any]] = []
    for key in ("externalIdentifier", "externalIdentifiers"):
        value = entity.get(key)
        if isinstance(value, list):
            identifiers.extend(item for item in value if isinstance(item, dict))
    return identifiers


def spdx3_package_purl(package: dict[str, Any]) -> str | None:
    """The package's purl: ``software_packageUrl`` first, else a purl-typed
    external identifier. None when the document carries neither."""
    direct = package.get("software_packageUrl")
    if isinstance(direct, str) and direct:
        return direct
    for ext_id in iter_spdx3_external_identifiers(package):
        if ext_id.get("externalIdentifierType") in _PURL_ID_TYPES:
            identifier = ext_id.get("identifier")
            if identifier:
                return str(identifier)
    return None


def has_spdx3_supplier(supplier_refs: list[Any], agents: dict[str, dict[str, Any]]) -> bool:
    """Whether any supplier ref resolves to an agent — the loop NTIA, CISA and
    FDA each carried privately, with a string-only guard that scored inline
    agents as no supplier."""
    return any(resolve_spdx3_agent(ref, agents) for ref in supplier_refs)


def extract_spdx3_elements(
    data: dict[str, Any],
) -> tuple[
    dict[str, Any] | None,
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    """Extract typed elements from @graph.

    Args:
        data: Parsed SPDX 3.0 SBOM dictionary.

    Returns:
        Tuple of (creation_info, packages, relationships, agents, tools),
        the maps keyed by spdxId. ``agents`` holds every Agent subtype —
        Person, Organization, SoftwareAgent, and bare Agent — because all of
        them are legal in creator and supplier positions.
    """
    elements = data.get("@graph", data.get("elements", []))
    # Untrusted uploads: an explicit null @graph reaches here as None and
    # would TypeError on iteration.
    if not isinstance(elements, list):
        elements = []

    creation_info: dict[str, Any] | None = None
    packages: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    agents: dict[str, dict[str, Any]] = {}
    tools: dict[str, dict[str, Any]] = {}

    for element in elements:
        # Untrusted documents: a non-dict entry or a null type must not take
        # the whole assessment run down.
        if not isinstance(element, dict):
            continue
        elem_type = element.get("type", element.get("@type", "")) or ""
        if not isinstance(elem_type, str):
            continue
        bare_type = elem_type.rsplit("/", 1)[-1]
        if "CreationInfo" in elem_type:
            creation_info = element
        elif "software_Package" in elem_type or elem_type == "Package":
            packages.append(element)
        elif "Relationship" in elem_type:
            relationships.append(element)
        elif bare_type in _AGENT_TYPES:
            spdx_id = element.get("spdxId", element.get("@id", ""))
            if spdx_id:
                agents[spdx_id] = element
        elif "Tool" in elem_type:
            spdx_id = element.get("spdxId", element.get("@id", ""))
            if spdx_id:
                tools[spdx_id] = element

    # Fall back to root-level creationInfo for legacy SPDX 3.x documents
    if creation_info is None:
        root_ci = data.get("creationInfo")
        if isinstance(root_ci, dict):
            creation_info = root_ci

    return creation_info, packages, relationships, agents, tools


def get_spdx3_creation_info_fields(
    creation_info: dict[str, Any] | None,
    persons_orgs: dict[str, dict[str, Any]],
    tools: dict[str, dict[str, Any]] | None = None,
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
        entity = resolve_spdx3_agent(ref, persons_orgs)
        name = entity.get("name", "")
        if name:
            creators.append(name)
        # Emails/URLs ride external identifiers, either spelling
        for ext_id in iter_spdx3_external_identifiers(entity):
            identifier = ext_id.get("identifier", "")
            if identifier:
                creators.append(identifier)

    # Extract tool names from createdUsing references. A SoftwareAgent lives
    # in the agents map, so the lookup checks both.
    tool_entries: list[str] = []
    refs = creation_info.get("createdUsing", [])
    if isinstance(refs, list):
        for ref in refs:
            if isinstance(ref, str):
                tool_element = tools.get(ref) or persons_orgs.get(ref)
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
    originated_by = package.get("originatedBy", [])
    if isinstance(originated_by, str):
        originated_by = [originated_by]
    elif not isinstance(originated_by, list):
        originated_by = []
    supplied_by = package.get("suppliedBy")
    if isinstance(supplied_by, str):
        supplied_by = [supplied_by]
    elif not isinstance(supplied_by, list):
        supplied_by = []
    supplier_refs = originated_by if originated_by else supplied_by
    download_location = package.get("software_downloadLocation", "")

    # Check for unique identifiers: the first-class purl property first, then
    # one scan of the external identifiers under either spelling — the purl
    # type variants are a subset of _UNIQUE_ID_TYPES, so no second pass.
    external_identifiers = iter_spdx3_external_identifiers(package)
    direct_purl = package.get("software_packageUrl")
    # The first-class content-addressable identifiers (gitoid/swhid) live on
    # software_contentIdentifier, distinct from externalIdentifier.
    content_identifiers = package.get("software_contentIdentifier")
    has_content_identifier = isinstance(content_identifiers, list) and any(
        isinstance(ci, dict) and ci.get("software_contentIdentifierValue") for ci in content_identifiers
    )
    has_unique_id = (
        bool(isinstance(direct_purl, str) and direct_purl)
        or has_content_identifier
        or any(ext_id.get("externalIdentifierType", "") in _UNIQUE_ID_TYPES for ext_id in external_identifiers)
    )

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


# Licensing element types from the SimpleLicensing and ExpandedLicensing
# profiles, matched on the unprefixed tail like every other type here. The
# NoAssertion/None singletons are collected too so a reference to them
# resolves deliberately to "no licence" rather than falling through as an
# unknown target.
# Spec spelling first (lowercase profile prefixes, per the 3.0.1 schema:
# simplelicensing_, expandedlicensing_), with the camelCase variants this
# module's reading rules extend to every other profile-prefixed name.
_LICENSE_TYPE_TAILS = frozenset(
    {
        "simplelicensing_LicenseExpression",
        "simplelicensing_SimpleLicensingText",
        "expandedlicensing_ListedLicense",
        "expandedlicensing_CustomLicense",
        "expandedlicensing_NoAssertionLicense",
        "expandedlicensing_NoneLicense",
        "simpleLicensing_LicenseExpression",
        "simpleLicensing_SimpleLicensingText",
        "expandedLicensing_ListedLicense",
        "expandedLicensing_CustomLicense",
        "expandedLicensing_NoAssertionLicense",
        "expandedLicensing_NoneLicense",
        "LicenseExpression",
        "SimpleLicensingText",
        "ListedLicense",
        "CustomLicense",
        "NoAssertionLicense",
        "NoneLicense",
    }
)

_NO_LICENSE_TAILS = frozenset(
    {
        "expandedlicensing_NoAssertionLicense",
        "expandedlicensing_NoneLicense",
        "expandedLicensing_NoAssertionLicense",
        "expandedLicensing_NoneLicense",
        "NoAssertionLicense",
        "NoneLicense",
    }
)


def extract_spdx3_licenses(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Licensing elements from @graph, keyed by spdxId.

    Kept separate from ``extract_spdx3_elements`` so its five-tuple contract
    (and every existing unpack site) stays untouched; the licence checks are
    the only consumers of this map.
    """
    elements = data.get("@graph", data.get("elements", []))
    if not isinstance(elements, list):
        return {}
    licenses: dict[str, dict[str, Any]] = {}
    for element in elements:
        if not isinstance(element, dict):
            continue
        elem_type = element.get("type", element.get("@type", "")) or ""
        if not isinstance(elem_type, str):
            continue
        if elem_type.rsplit("/", 1)[-1] not in _LICENSE_TYPE_TAILS:
            continue
        spdx_id = element.get("spdxId", element.get("@id", ""))
        if isinstance(spdx_id, str) and spdx_id:
            licenses[spdx_id] = element
    return licenses


def resolve_spdx3_license_expression(target: Any, licenses: dict[str, dict[str, Any]]) -> str | None:
    """The licence string a relationship target denotes, or ``None``.

    Resolution order: a LicenseExpression's expression string, then a
    Listed/Custom licence's name, then the SPDX licence-list id tail for a
    ``spdx.org/licenses/…`` reference that carries no element (the
    conventional way documents cite listed licences). NoAssertion/None
    singletons and anything unresolvable are ``None`` — a reference to
    nothing must not score as a licence.
    """
    element: dict[str, Any] | None
    if isinstance(target, dict):
        element = target
    elif isinstance(target, str):
        element = licenses.get(target)
    else:
        return None

    if element is None:
        if isinstance(target, str) and "spdx.org/licenses/" in target:
            tail = target.rstrip("/").rsplit("/", 1)[-1]
            return tail or None
        return None

    elem_type = element.get("type", element.get("@type", "")) or ""
    if isinstance(elem_type, str) and elem_type.rsplit("/", 1)[-1] in _NO_LICENSE_TAILS:
        return None

    expression = element.get("simplelicensing_licenseExpression", element.get("simpleLicensing_licenseExpression"))
    if isinstance(expression, str) and expression.strip():
        return expression.strip()
    name = element.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    spdx_id = element.get("spdxId", element.get("@id", ""))
    if isinstance(spdx_id, str) and "spdx.org/licenses/" in spdx_id:
        tail = spdx_id.rstrip("/").rsplit("/", 1)[-1]
        return tail or None
    return None


def get_spdx3_package_license(
    package: dict[str, Any],
    relationships: list[dict[str, Any]],
    licenses: dict[str, dict[str, Any]],
    relationship_type: str,
) -> str | None:
    """The resolved licence for ``package`` via ``relationship_type``.

    ``hasConcludedLicense`` and ``hasDeclaredLicense`` relationships point
    from the package at licensing elements; the first resolvable target wins.
    ``None`` when no relationship exists or every target is unresolvable —
    the callers treat both as the same failure, deliberately.
    """
    pkg_id = package.get("spdxId", package.get("@id", ""))
    if not pkg_id:
        return None
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        if rel.get("from") != pkg_id or rel.get("relationshipType") != relationship_type:
            continue
        targets = rel.get("to", [])
        if isinstance(targets, (str, dict)):
            targets = [targets]
        if not isinstance(targets, list):
            continue
        for target in targets:
            resolved = resolve_spdx3_license_expression(target, licenses)
            if resolved:
                return resolved
    return None
