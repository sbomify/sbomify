"""Keep releases' VEX pins pointing at their components' newest VEX.

A VEX is a living judgment document: when a component gets a newer imported VEX
(manual upload or Dependency-Track triage sync), every release that ships that
component's SBOM should serve the new statements. In-app triage VEX is never
pinned here — it is a component-level overlay applied on top of the pinned
imported VEX at resolution time, so it never evicts an imported pin — the exploitability of a
past release changes when the analysis does, not when the release is cut.

Provenance rule: pins created here are marked ``auto_pinned`` and only ever
replace other auto pins. A VEX a user pinned by hand is an authoritative
snapshot for that release (it outranks the component's latest during scan
annotation) and is never touched.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def ensure_latest_vex_pinned(release: Any, component: Any, latest_vex: Any = None) -> bool:
    """Auto-pin the component's newest VEX to the release.

    No-op when the component has no VEX, when a *manual* VEX pin for this
    component already exists on the release (deliberate snapshot — it wins),
    or when the newest VEX is already pinned. ``latest_vex`` lets batch
    callers resolve the newest VEX once instead of once per release. Returns
    True when the pin changed.
    """
    from sbomify.apps.core.models import Release, ReleaseArtifact, _suppress_collection_signals
    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.vulnerability_scanning.vex import TRIAGE_SOURCE

    if latest_vex is None:
        latest_vex = (
            SBOM.objects.filter(component=component, bom_type=SBOM.BomType.VEX.value)
            .exclude(source=TRIAGE_SOURCE)
            .order_by("-created_at")
            .first()
        )
    if latest_vex is None:
        return False

    vex_pins = release.artifacts.filter(sbom__component=component, sbom__bom_type=SBOM.BomType.VEX.value)
    if vex_pins.filter(auto_pinned=False).exists():
        return False
    if vex_pins.filter(sbom=latest_vex).exists():
        return False

    # Suppress the per-row collection bumps during the replace (the delete and
    # the create would otherwise bump REMOVED + ADDED) and bump once with the
    # accurate reason, mirroring Release.add_artifact_to_latest_release.
    token = _suppress_collection_signals.set(True)
    try:
        replaced, _ = vex_pins.filter(auto_pinned=True).delete()
        ReleaseArtifact.objects.create(release=release, sbom=latest_vex, auto_pinned=True)
    finally:
        _suppress_collection_signals.reset(token)
    release.bump_collection_version(
        Release.CollectionUpdateReason.ARTIFACT_UPDATED if replaced else Release.CollectionUpdateReason.ARTIFACT_ADDED
    )
    logger.info(
        "Auto-pinned VEX %s of component %s to release %s",
        latest_vex.id,
        component.id,
        release.id,
    )
    return True


def refresh_vex_pins_for_component(component_id: str) -> int:
    """Re-point the auto VEX pin on every release that ships this component's SBOM.

    Called when a component gains a new VEX. Manual pins are left alone.
    Returns the number of releases whose pin changed.
    """
    from sbomify.apps.core.models import Component, Release
    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.vulnerability_scanning.vex import TRIAGE_SOURCE

    component = Component.objects.filter(id=component_id).first()
    if component is None:
        return 0

    latest_vex = (
        SBOM.objects.filter(component=component, bom_type=SBOM.BomType.VEX.value)
        .exclude(source=TRIAGE_SOURCE)
        .order_by("-created_at")
        .first()
    )
    if latest_vex is None:
        return 0

    releases = Release.objects.filter(
        artifacts__sbom__component=component,
        artifacts__sbom__bom_type=SBOM.BomType.SBOM.value,
    ).distinct()

    changed = 0
    for release in releases:
        if ensure_latest_vex_pinned(release, component, latest_vex=latest_vex):
            changed += 1
    return changed
