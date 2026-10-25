"""Keep releases' VEX pins pointing at the VEX written for the versions they ship.

A VEX is a statement about one version of a component: "not affected" was
verified against that build, and nothing says it still holds for the next one.
So a release carries a component's VEX only when the VEX was written for the
version of the component's SBOM in that release. A newer VEX for the same
version (a re-issued upload, a Dependency-Track triage sync) replaces the pin;
a VEX written for another version never reaches the release. In-app triage VEX
is never pinned here — it is a component-level overlay applied on top at
resolution time.

Provenance rule: pins created here are marked ``auto_pinned`` and only ever
replace other auto pins. A VEX a user pinned by hand is an authoritative
snapshot for that release (it outranks version matching during scan
annotation) and is never touched.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _shipped_version_keys(release: Any, component: Any) -> set[str]:
    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.vulnerability_scanning.vex import vex_version_key

    versions = release.artifacts.filter(sbom__component=component, sbom__bom_type=SBOM.BomType.SBOM.value).values_list(
        "sbom__version", flat=True
    )
    return {key for version in versions if (key := vex_version_key(version)) is not None}


def _wanted_vex_ids(component: Any, version_keys: set[str]) -> set[Any]:
    """The newest imported VEX per (version, source) among the versions the release ships."""
    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.vulnerability_scanning.vex import TRIAGE_SOURCE, vex_version_key

    if not version_keys:
        return set()
    rows = (
        SBOM.objects.filter(component=component, bom_type=SBOM.BomType.VEX.value)
        .exclude(source=TRIAGE_SOURCE)
        .order_by("-created_at")
        .values_list("id", "version", "source")
    )
    newest: dict[tuple[str, str], Any] = {}
    for vex_id, version, source in rows.iterator():
        key = vex_version_key(version)
        if key in version_keys:
            newest.setdefault((key, source or ""), vex_id)
    return set(newest.values())


def sync_vex_pins(release: Any, component: Any, *, bump: bool = True) -> bool:
    """Make the release's auto VEX pins for ``component`` match the versions it ships.

    Pins the newest VEX per source written for each version of the component's
    SBOM in the release, and drops any auto pin whose VEX was written for a
    version the release does not ship. No-op when a *manual* VEX pin for this
    component exists on the release (deliberate snapshot — it wins). Returns
    True when the pins changed. ``bump=False`` is for bulk latest-release
    maintenance, which bumps the collection version once itself.
    """
    from sbomify.apps.core.models import Release, ReleaseArtifact, _suppress_collection_signals
    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.vulnerability_scanning.vex import TRIAGE_SOURCE

    vex_pins = release.artifacts.filter(sbom__component=component, sbom__bom_type=SBOM.BomType.VEX.value).exclude(
        sbom__source=TRIAGE_SOURCE
    )
    if vex_pins.filter(auto_pinned=False).exists():
        return False

    wanted = _wanted_vex_ids(component, _shipped_version_keys(release, component))
    current = set(vex_pins.values_list("sbom_id", flat=True))
    if wanted == current:
        return False

    # Suppress the per-row collection bumps during the replace (the delete and
    # the create would otherwise bump REMOVED + ADDED) and bump once with the
    # accurate reason, mirroring Release.add_artifact_to_latest_release.
    token = _suppress_collection_signals.set(True)
    try:
        removed, _ = vex_pins.exclude(sbom_id__in=wanted).delete()
        for vex_id in wanted - current:
            ReleaseArtifact.objects.create(release=release, sbom_id=vex_id, auto_pinned=True)
    finally:
        _suppress_collection_signals.reset(token)
    if not bump:
        return True
    if not wanted:
        reason = Release.CollectionUpdateReason.ARTIFACT_REMOVED
    elif removed:
        reason = Release.CollectionUpdateReason.ARTIFACT_UPDATED
    else:
        reason = Release.CollectionUpdateReason.ARTIFACT_ADDED
    release.bump_collection_version(reason)
    logger.info("Synced VEX pins of component %s on release %s", component.id, release.id)
    return True


def refresh_vex_pins_for_component(component_id: str) -> int:
    """Re-sync the auto VEX pins on every release that ships this component's SBOM.

    Called when a component gains a new VEX. Manual pins are left alone.
    Returns the number of releases whose pins changed.
    """
    from sbomify.apps.core.models import Component, Release
    from sbomify.apps.sboms.models import SBOM

    component = Component.objects.filter(id=component_id).first()
    if component is None:
        return 0

    releases = Release.objects.filter(
        artifacts__sbom__component=component,
        artifacts__sbom__bom_type=SBOM.BomType.SBOM.value,
    ).distinct()

    changed = 0
    for release in releases:
        if sync_vex_pins(release, component):
            changed += 1
    return changed
