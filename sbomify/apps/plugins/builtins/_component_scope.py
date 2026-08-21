"""Which CycloneDX components the software compliance plugins score.

NTIA 2021, BSI TR-03183-2, CISA 2025 and FDA premarket all define their
per-component fields — supplier, version, purl/cpe/swid, hash, licence — for
*software packages*. Two CycloneDX component types are not software packages
and fail those fields by construction, so grading them measures the
vocabulary mismatch rather than the producer's compliance:

``file``
    Generators such as syft emit an entry for their own scan input (a
    lockfile, a manifest). Input metadata, not something that ships.

``device``
    A physical part: a chip, a board, a connector. purl has no hardware
    namespace and ``version`` carries a part revision rather than a release.
    Vendor is the partial case: CycloneDX records it in ``manufacturer``, which
    BSI's per-component creator check does read (``bsi.py`` ``_get_cyclonedx_
    component_creator``) while NTIA, CISA and FDA read only ``supplier`` and
    ``publisher``. Exempting the whole type therefore gives up one check a
    hardware BOM could have passed, in exchange for one rule across four
    plugins. Teaching the other three to read ``manufacturer`` is the better
    answer and a change to what those frameworks score, so it is filed
    separately rather than smuggled in here.

Deliberately *not* exempt, even though hardware BOMs list them alongside the
device: ``firmware``, ``device-driver`` and ``platform`` are software. They
ship with a vendor, a real release version and often a package identifier, so
the software minimum elements apply to them unchanged.

Component name stays mandatory for every type — a nameless entry is a data
quality defect whatever it describes.

CycloneDX only. The SPDX paths in these plugins exempt file entries too, by
``"-File-" in SPDXID`` rather than by a type field, so they are a parallel
worth keeping in step: SPDX 2.3's ``primaryPackagePurpose: DEVICE`` is the
hardware analogue and nothing reads it today.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

NON_SOFTWARE_COMPONENT_TYPES = frozenset({"device", "file"})


def is_non_software_component(component: Mapping[str, Any]) -> bool:
    """Return True when the per-component software checks do not apply.

    Args:
        component: A CycloneDX ``components[]`` entry.

    Returns:
        True for the non-software component types, False for everything else
        (including an absent or unrecognised ``type``, which stays graded).
    """
    return str(component.get("type", "")).lower() in NON_SOFTWARE_COMPONENT_TYPES
