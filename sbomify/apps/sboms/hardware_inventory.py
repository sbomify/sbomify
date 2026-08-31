"""Derive a hardware (HBOM) parts inventory from a CycloneDX document.

CycloneDX has no hardware sub-schema. An HBOM is an ordinary document whose
components are typed ``device`` / ``firmware`` / ``device-driver`` /
``platform``, with the part detail — quantity, function, board location, GS1
identifiers, certifications — carried in the ``cdx:device`` namespace of the
component property bag. sbomify stores the artifact immutably (ADR-004), so the
inventory is **derived on read**: nothing here is persisted or written back.

The ``cdx:device`` namespace is the official CycloneDX property taxonomy
(``CycloneDX/cyclonedx-property-taxonomy``), versioned separately from the
schema and never schema-validated — a document can be schema-valid with a
property bag full of anything. Every reader below therefore treats the bag as
untrusted input: a ``properties`` value that is not a list, entries missing
``name``, non-string values and unparseable certification keys all degrade to a
missing field instead of raising.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from botocore.exceptions import BotoCoreError, ClientError
from django.core.cache import cache as django_cache
from django.http import HttpRequest

from sbomify.apps.core.authz import can
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.core.url_utils import safe_external_url
from sbomify.apps.sboms.models import SBOM

# The same set that decides a document is an HBOM. Detection and projection must
# never diverge: a stricter set here renders an HBOM page with an empty parts
# table, a looser one lists parts on a document nothing calls hardware.
from sbomify.apps.sboms.utils import _HBOM_COMPONENT_TYPES as HARDWARE_TYPES

log = logging.getLogger(__name__)

DEVICE_PROPERTY_PREFIX = "cdx:device:"
GS1_PROPERTY_PREFIX = "cdx:device:gs1:"
CERTIFICATION_PROPERTY_PREFIX = "cdx:device:certifications:"

# 1.7 states a device containing firmware SHOULD carry a linked firmware or
# operating-system component; the link itself lives in the dependency graph.
_FIRMWARE_TYPES = frozenset({"firmware", "operating-system"})

_NVD_CPE_SEARCH_URL = "https://nvd.nist.gov/products/cpe/search/results"


@dataclass(frozen=True)
class Certification:
    """One regulatory approval, from ``cdx:device:certifications:<country>:<authority>:id|url``."""

    country: str  # ISO 3166-1
    authority: str
    identifier: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class HardwarePart:
    """One hardware component, projected into BOM-line shape."""

    name: str | None  # the official example carries the manufacturer part number here
    bom_ref: str | None
    type: str | None  # device | firmware | device-driver | platform
    manufacturer: str | None = None
    # Which field the manufacturer came from — a supplier or publisher is a
    # fallback, not the manufacturer, and the UI says so rather than implying
    # provenance the document never claimed.
    manufacturer_source: str | None = None
    revision: str | None = None
    quantity: str | None = None
    function: str | None = None
    location: str | None = None  # board location
    device_type: str | None = None
    sku: str | None = None
    serial_number: str | None = None
    lot_number: str | None = None
    prod_timestamp: str | None = None
    mac_address: str | None = None
    gs1: tuple[tuple[str, str], ...] = ()  # (identifier kind, value), e.g. ("gtin-12", "8223...")
    certifications: tuple[Certification, ...] = ()
    datasheets: tuple[str, ...] = ()
    cpe: str | None = None
    firmware: tuple[str, ...] = ()  # linked firmware / OS components, from the dependency graph


@dataclass(frozen=True)
class HardwareInventory:
    """The hardware parts derived from a single CycloneDX document."""

    parts: tuple[HardwarePart, ...] = ()

    @property
    def count(self) -> int:
        return len(self.parts)

    @property
    def by_type(self) -> dict[str, int]:
        """Count of parts per component ``type``."""
        return dict(Counter(p.type for p in self.parts if p.type))


def _str_or_none(value: Any) -> str | None:
    """Coerce a CycloneDX scalar to ``str``; drop anything structured."""
    if value is None or isinstance(value, str):
        return value or None
    if isinstance(value, (int, float)):  # bool is an int subclass — fine
        return str(value)
    return None


def _properties(component: dict[str, Any]) -> dict[str, str]:
    """Flatten a property bag — a ``list`` of ``{name, value}`` — into a mapping.

    First occurrence wins: the schema permits duplicate names, and a later entry
    overwriting an earlier one would let a trailing property mask a leading one.
    """
    bag = component.get("properties")
    if not isinstance(bag, list):
        return {}
    flat: dict[str, str] = {}
    for entry in bag:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        value = _str_or_none(entry.get("value"))
        if isinstance(name, str) and name and value is not None and name not in flat:
            flat[name] = value
    return flat


def _gs1_identifiers(properties: dict[str, str]) -> tuple[tuple[str, str], ...]:
    """GS1 keys keyed by identifier kind (gtin-8/12/13/14, giai, gln, gmn, epcRfid).

    Matched by prefix rather than an allow-list: the taxonomy adds identifier
    kinds without a schema release, and an unknown kind is still worth showing.
    """
    return tuple(
        (key[len(GS1_PROPERTY_PREFIX) :], value)
        for key, value in properties.items()
        if key.startswith(GS1_PROPERTY_PREFIX) and len(key) > len(GS1_PROPERTY_PREFIX)
    )


def _certifications(properties: dict[str, str]) -> tuple[Certification, ...]:
    """Group ``cdx:device:certifications:<country>:<authority>:id|url`` pairs.

    Two of the key's segments are variable, so it is parsed rather than looked
    up. An authority containing a colon keeps its colon: the trailing segment is
    the field name and everything between country and field is the authority.
    """
    grouped: dict[tuple[str, str], dict[str, str]] = {}
    for key, value in properties.items():
        if not key.startswith(CERTIFICATION_PROPERTY_PREFIX):
            continue
        segments = key[len(CERTIFICATION_PROPERTY_PREFIX) :].split(":")
        if len(segments) < 3:
            continue
        country, *authority, field = segments
        if field.lower() not in ("id", "url"):
            continue
        grouped.setdefault((country, ":".join(authority)), {})[field.lower()] = value
    return tuple(
        Certification(
            country=country,
            authority=authority,
            identifier=fields.get("id"),
            # Uploader-controlled, same as a datasheet link.
            url=safe_external_url(fields.get("url")) or None,
        )
        for (country, authority), fields in grouped.items()
    )


def _manufacturer(component: dict[str, Any]) -> tuple[str | None, str | None]:
    """``(name, source_field)`` from ``manufacturer`` (1.6+), then ``supplier``, then ``publisher``."""
    for field in ("manufacturer", "supplier"):
        entity = component.get(field)
        if isinstance(entity, dict) and (name := _str_or_none(entity.get("name"))):
            return name, field
    publisher = _str_or_none(component.get("publisher"))
    return (publisher, "publisher") if publisher else (None, None)


def _datasheets(component: dict[str, Any]) -> tuple[str, ...]:
    references = component.get("externalReferences")
    if not isinstance(references, list):
        return ()
    # Filtered here rather than in the template so the API response carries the
    # same values the page does: a document can name a javascript: URL in an
    # externalReference, and ADR-004 means we store it exactly as received.
    return tuple(
        url
        for reference in references
        if isinstance(reference, dict)
        and reference.get("type") == "documentation"
        and (url := safe_external_url(reference.get("url")))
    )


def _cpe_fields(cpe: str) -> list[str]:
    """Split a CPE 2.3 name on its unescaped colons.

    A field may contain an escaped colon (``\\:``), so a plain ``split(":")``
    over-counts and a ``count(":")`` well-formedness test rejects valid names.
    """
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for char in cpe:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            current.append(char)
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def nvd_cpe_url(cpe: str) -> str:
    """NVD product search for a hardware CPE — an operator lookup, not a scan.

    Hardware CPEs are unversioned and the advisory feeds carry almost no
    ``part:h`` identifiers, so matching them to CVEs automatically produces
    noise. The link hands the part to a human instead, who picks the exact
    entry and follows it to whatever CVEs reference it.

    The target is the CPE dictionary rather than the vulnerability search.
    NVD replaced the query-parameter vulnerability results endpoint with a
    single-page app whose only input is a keyword, and that keyword search does
    not match a CPE string: searching the dictionary for the full 2.3 name of a
    real Intel part returns nothing, while its vendor and product as separate
    terms return hundreds of entries. So the vendor and product are what get
    sent, and an empty string comes back when the name yields neither, since a
    link that lands on "no results" is worse than no link.
    """
    if not cpe.startswith("cpe:2.3:"):
        return ""
    fields = _cpe_fields(cpe)
    # cpe:2.3:part:vendor:product:... — indices 3 and 4.
    if len(fields) < 5:
        return ""
    terms = [f.replace("\\", "") for f in fields[3:5] if f and f not in ("*", "-")]
    if not terms:
        return ""
    return f"{_NVD_CPE_SEARCH_URL}?{urlencode({'namingFormat': '2.3', 'keyword': ' '.join(terms)})}"


def _label(component: dict[str, Any]) -> str:
    """Display label for a linked component: name plus version, or its bom-ref."""
    name = _str_or_none(component.get("name"))
    version = _str_or_none(component.get("version"))
    if name and version:
        return f"{name} {version}"
    return name or _str_or_none(component.get("bom-ref")) or "unnamed"


def _firmware_by_ref(document: dict[str, Any], components: list[dict[str, Any]]) -> dict[str, tuple[str, ...]]:
    """Map each bom-ref to the firmware/OS components it depends on."""
    labels = {
        ref: _label(component)
        for component in components
        if component.get("type") in _FIRMWARE_TYPES and isinstance(ref := component.get("bom-ref"), str) and ref
    }
    dependencies = document.get("dependencies")
    if not labels or not isinstance(dependencies, list):
        return {}
    linked: dict[str, list[str]] = {}
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            continue
        ref = dependency.get("ref")
        depends_on = dependency.get("dependsOn")
        if not isinstance(ref, str) or not isinstance(depends_on, list):
            continue
        for target in depends_on:
            if isinstance(target, str) and target != ref and target in labels:
                linked.setdefault(ref, []).append(labels[target])
    return {ref: tuple(names) for ref, names in linked.items()}


def _project_part(component: dict[str, Any], firmware_by_ref: dict[str, tuple[str, ...]]) -> HardwarePart:
    properties = _properties(component)
    manufacturer, manufacturer_source = _manufacturer(component)
    bom_ref = _str_or_none(component.get("bom-ref"))
    return HardwarePart(
        name=_str_or_none(component.get("name")),
        bom_ref=bom_ref,
        type=_str_or_none(component.get("type")),
        manufacturer=manufacturer,
        manufacturer_source=manufacturer_source,
        revision=_str_or_none(component.get("version")),
        quantity=properties.get("cdx:device:quantity"),
        function=properties.get("cdx:device:function"),
        location=properties.get("cdx:device:location"),
        device_type=properties.get("cdx:device:deviceType"),
        sku=properties.get("cdx:device:sku"),
        serial_number=properties.get("cdx:device:serialNumber"),
        lot_number=properties.get("cdx:device:lotNumber"),
        prod_timestamp=properties.get("cdx:device:prodTimestamp"),
        mac_address=properties.get("cdx:device:macAddress"),
        gs1=_gs1_identifiers(properties),
        certifications=_certifications(properties),
        datasheets=_datasheets(component),
        cpe=_str_or_none(component.get("cpe")),
        firmware=firmware_by_ref.get(bom_ref or "", ()),
    )


def _hardware_parts(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hardware-typed components in document order, one part per ``bom-ref``.

    A ref repeated inside one document is a duplicate entry rather than a second
    part, and the release merge collapses it the same way — without this, a
    generator that names the board in both ``metadata.component`` and
    ``components`` would list it twice here and once there.
    """
    parts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for component in components:
        if component.get("type") not in HARDWARE_TYPES:
            continue
        ref = component.get("bom-ref")
        if isinstance(ref, str) and ref:
            if ref in seen:
                continue
            seen.add(ref)
        parts.append(component)
    return parts


def part_search_term(part: dict[str, Any]) -> str:
    """Everything the client-side search matches a part on, pre-lowercased."""
    fields = (
        part.get("name"),
        part.get("manufacturer"),
        part.get("revision"),
        part.get("type"),
        part.get("function"),
        part.get("location"),
        part.get("device_type"),
        part.get("sku"),
        part.get("serial_number"),
        part.get("cpe"),
        *(part.get("gs1") or {}).values(),
        *(c.get("identifier") or "" for c in part.get("certifications") or []),
    )
    return " ".join(str(f) for f in fields if f).lower()


def derive_hardware_inventory(document: object, *, include_root: bool = False) -> HardwareInventory:
    """Project the hardware components of a CycloneDX document into a parts list.

    ``metadata.component`` is the subject the document describes — the assembled
    board — rather than a line on its own bill of materials, so it is lifted in
    only when ``include_root`` is set, and then only when it carries a hardware
    type. Display paths set it, matching the release merge in ``hbom.py``: an
    artifact naming its device only in ``metadata.component`` is stamped
    hardware-bearing at upload, so a page selects it *because* it holds hardware
    and would otherwise render "no parts" for the board the merged release HBOM
    lists. Assessment leaves it off — the HBOM plugin scores that component
    separately as the final-goods assembly, and an assembly has no quantity or
    board location of its own to score as a part.

    Parts keep document order, the lifted root last, which is the order the
    merged release HBOM carries. Returns an empty inventory for a non-dict input
    or a document with no hardware components. Never raises on partial or
    hostile data.
    """
    if not isinstance(document, dict):
        return HardwareInventory()
    raw = document.get("components")
    components = [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []
    if include_root:
        metadata = document.get("metadata")
        root = metadata.get("component") if isinstance(metadata, dict) else None
        # Any hardware root, not only ``device`` — the same predicate the merge
        # applies, so a board rooted at a ``platform`` is lifted by both.
        if isinstance(root, dict) and root.get("type") in HARDWARE_TYPES:
            components.append(root)
    parts = _hardware_parts(components)
    if not parts:
        return HardwareInventory()
    firmware_by_ref = _firmware_by_ref(document, components)
    return HardwareInventory(parts=tuple(_project_part(c, firmware_by_ref) for c in parts))


def serialize_part(part: HardwarePart) -> dict[str, Any]:
    """Flatten a part for the API and the card template."""
    return {
        "name": part.name,
        "bom_ref": part.bom_ref,
        "type": part.type,
        "manufacturer": part.manufacturer,
        "manufacturer_source": part.manufacturer_source,
        "revision": part.revision,
        "quantity": part.quantity,
        "function": part.function,
        "location": part.location,
        "device_type": part.device_type,
        "sku": part.sku,
        "serial_number": part.serial_number,
        "lot_number": part.lot_number,
        "prod_timestamp": part.prod_timestamp,
        "mac_address": part.mac_address,
        "gs1": dict(part.gs1),
        "certifications": [
            {"country": c.country, "authority": c.authority, "identifier": c.identifier, "url": c.url}
            for c in part.certifications
        ],
        "datasheets": list(part.datasheets),
        "cpe": part.cpe,
        "cpe_nvd_url": nvd_cpe_url(part.cpe) if part.cpe else None,
        "firmware": list(part.firmware),
    }


def get_hardware_inventory(request: HttpRequest, sbom_id: str) -> ServiceResult[dict[str, Any]]:
    """Derive the hardware (HBOM) parts inventory for an SBOM.

    Reads the immutable artifact from storage and projects its hardware
    components (ADR-004 — nothing is persisted or mutated). Returns an empty
    inventory when the artifact carries no hardware components or is not a
    parseable CycloneDX document.
    """
    try:
        sbom = SBOM.objects.select_related("component", "component__team").get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return ServiceResult.failure("SBOM not found", status_code=404)

    # Route through can() so a scoped API token's read scope is honoured (this
    # endpoint runs optional_auth, so a PAT reaches it). component:access is the
    # ABAC read action; no change for sessions / full / read-only tokens.
    if not can(request, "component:access", sbom.component):
        return ServiceResult.failure("Forbidden", status_code=403)

    if not sbom.sbom_filename:
        return ServiceResult.failure("SBOM file not found", status_code=404)

    # The artifact is immutable (ADR-004), so the derived inventory is a pure
    # function of the SBOM id: cache it after the per-request access check.
    # Bump the version key when the derivation shape changes.
    cache_key = f"hardware-inventory:v2:{sbom.id}"
    cached = django_cache.get(cache_key)
    if cached is not None:
        return ServiceResult.success(cached)

    try:
        raw = S3Client("SBOMS").get_sbom_data(sbom.sbom_filename)
    except (BotoCoreError, ClientError) as exc:
        # The card is best-effort and lazy-loaded after page render: ANY storage
        # failure must collapse it, never 500. A genuinely missing object is
        # "not found" (same as the SBOM download path); everything else —
        # unreachable store, NoSuchBucket, AccessDenied, bad credentials — is
        # reported as temporarily unavailable.
        code = exc.response.get("Error", {}).get("Code") if isinstance(exc, ClientError) else None
        if code in ("NoSuchKey", "404"):
            return ServiceResult.failure("SBOM file not found", status_code=404)
        log.warning(
            "Hardware inventory: object store error (%s) for SBOM %s", code or "connection", sbom_id, exc_info=True
        )
        return ServiceResult.failure("SBOM file unavailable", status_code=503)
    if not raw:  # None or empty body == missing/corrupt artifact (matches download_sbom)
        return ServiceResult.failure("SBOM file not found", status_code=404)

    try:
        document = json.loads(raw)
    except (ValueError, TypeError):
        # ValueError covers JSONDecodeError and UnicodeDecodeError (non-UTF-8 bytes),
        # so a corrupt artifact degrades to an empty inventory rather than a 500.
        document = None

    # A read path: the device the document describes is a part on this page, as
    # it is a component of the merged release HBOM.
    inventory = derive_hardware_inventory(document if isinstance(document, dict) else None, include_root=True)
    payload = {
        "sbom_id": str(sbom.id),
        "component_id": str(sbom.component.id),
        "count": inventory.count,
        "by_type": inventory.by_type,
        "parts": [serialize_part(p) for p in inventory.parts],
    }
    django_cache.set(cache_key, payload, 3600)
    return ServiceResult.success(payload)
