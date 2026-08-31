"""Which CycloneDX components the software compliance plugins score.

NTIA 2021, BSI TR-03183-2, CISA 2025 and FDA premarket all define their
per-component fields — supplier, version, purl/cpe/swid, hash, licence — for
*software packages*. Two CycloneDX component types are not software packages
and fail those fields by construction, so grading them measures the
vocabulary mismatch rather than the producer's compliance:

``file``
    Generators such as syft emit an entry for their own scan input (a
    lockfile, a manifest). Input metadata, not something that ships, and
    nobody supplies it — exempt from every per-component field.

``device``
    A physical part: a chip, a board, a connector. purl has no hardware
    namespace and ``version`` carries a part revision rather than a release,
    so identifiers and version do not apply. Supplier does: CycloneDX records
    a hardware vendor in ``component.manufacturer``, which
    ``get_component_supplier`` reads alongside ``publisher`` and ``supplier``.
    A device is therefore graded on supplier and exempt from the rest.

Deliberately *not* exempt, even though hardware BOMs list them alongside the
device: ``firmware``, ``device-driver`` and ``platform`` are software. They
ship with a vendor, a real release version and often a package identifier, so
the software minimum elements apply to them unchanged.

Component name stays mandatory for every type — a nameless entry is a data
quality defect whatever it describes.

When every component in a document was exempt from an element, that element's
empty failure list means "nothing was checked", not "everything passed", so
``element_verdict`` reports ``warning``. A document with no components at all
keeps whatever it scores today: that is a different defect.

CycloneDX only. The SPDX paths in these plugins exempt file entries too, by
``"-File-" in SPDXID`` rather than by a type field, so they are a parallel
worth keeping in step: SPDX 2.3's ``primaryPackagePurpose: DEVICE`` is the
hardware analogue and nothing reads it today.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

NON_SOFTWARE_COMPONENT_TYPES = frozenset({"device", "file"})

# A device names its vendor in `manufacturer`, so supplier is gradeable on it.
# A file entry is the generator's own scan input and has no vendor at all.
SUPPLIER_EXEMPT_COMPONENT_TYPES = frozenset({"file"})

NOT_GRADED_DETAIL = (
    "Not graded: every component in this document is a non-software entry "
    "(CycloneDX type device or file) that this check does not apply to."
)


def _component_type(component: Mapping[str, Any]) -> str:
    return str(component.get("type", "")).lower()


def is_non_software_component(component: Mapping[str, Any]) -> bool:
    """Return True when the per-component software checks do not apply.

    Args:
        component: A CycloneDX ``components[]`` entry.

    Returns:
        True for the non-software component types, False for everything else
        (including an absent or unrecognised ``type``, which stays graded).
    """
    return _component_type(component) in NON_SOFTWARE_COMPONENT_TYPES


def is_supplier_exempt(component: Mapping[str, Any]) -> bool:
    """Return True when the component has no supplier to name.

    Narrower than :func:`is_non_software_component`: it covers the supplier
    element only, which BSI calls the component creator.
    """
    return _component_type(component) in SUPPLIER_EXEMPT_COMPONENT_TYPES


def get_component_supplier(component: Mapping[str, Any]) -> str | None:
    """Return the name of the entity that supplied this component, or None.

    CycloneDX spreads the vendor across three fields: ``publisher`` (a plain
    string) plus ``supplier`` and ``manufacturer``, both organisational
    entities. ``manufacturer`` (1.6+) is the one a hardware generator
    populates for a physical part, and any of the three names the entity that
    NTIA, CISA and FDA ask for.

    A field holding something other than the shape the spec defines is
    ignored rather than trusted: these documents are uploaded by third
    parties, and a list in ``publisher`` names nobody.
    """
    publisher = component.get("publisher")
    if isinstance(publisher, str) and publisher:
        return publisher
    for field in ("supplier", "manufacturer"):
        entity = component.get(field)
        if isinstance(entity, Mapping):
            name = entity.get("name")
            if isinstance(name, str) and name:
                return name
    return None


def nothing_to_grade(
    components: Sequence[Mapping[str, Any]],
    exempt: Callable[[Mapping[str, Any]], bool] = is_non_software_component,
) -> bool:
    """Return True when the document had components and every one is exempt.

    The empty document is deliberately False. No components at all is its own
    defect, and redefining what it scores is not this rule's job.
    """
    return bool(components) and all(exempt(component) for component in components)


def element_verdict(
    failures: Sequence[str],
    nothing_graded: bool,
    missing_detail: str | None = None,
    *,
    missing_status: str = "fail",
    clean_detail: str | None = None,
    not_graded_detail: str | None = None,
) -> tuple[str, str | None]:
    """Return the ``(status, details)`` for one per-component element.

    Args:
        failures: Names of the components that missed the element.
        nothing_graded: True when every component was exempt from it — see
            :func:`nothing_to_grade`.
        missing_detail: Detail line for the failures, defaulting to a plain
            listing. BSI passes its own truncating formatter.
        missing_status: What a non-empty ``failures`` scores. ``warning`` for
            the BSI fields that are only advisory.
        clean_detail: Detail line for a clean, non-empty grading run.
        not_graded_detail: Detail line when nothing was graded. The default
            names the device-and-file exemption; a check whose exemption set
            differs (supplier grading applies to devices) passes its own.
    """
    if failures:
        return missing_status, missing_detail if missing_detail is not None else f"Missing for: {', '.join(failures)}"
    if nothing_graded:
        return "warning", not_graded_detail if not_graded_detail is not None else NOT_GRADED_DETAIL
    return "pass", clean_detail
