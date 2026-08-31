"""Merge a release's HBOM (Hardware BOM) artifacts into one document.

A release can pin an HBOM per component. Consumers of the Trust Center want a
single hardware BOM for the release, so this unions the hardware components
(and their dependency edges) of the newest HBOM in each component's release
slot into one CycloneDX document — the same shape as the merged VEX and CBOM
downloads.

Unlike the CBOM merge there is no vocabulary to translate between lineages: the
hardware component *types* are unchanged since 1.5, so none of CBOM's crypto
down-conversion applies here.

There is still one version concern. 1.7 added three generic Component fields —
``isExternal``, ``patentAssertions`` and ``versionRange`` — that apply to a
``device`` as much as to a library, and the 1.6 schema forbids unknown keys. A
release can pin a 1.7 HBOM (uploads accept 1.3 through 1.7), so copying its
components verbatim into a document stamped 1.6 would emit a file sbomify itself
rejects on re-upload. Those keys are dropped when emitting 1.6.
"""

from __future__ import annotations

import json
import uuid
from functools import lru_cache
from typing import Any

from sbomify.logging import getLogger

logger = getLogger(__name__)


def _component_keys(model: Any) -> set[str]:
    """The JSON keys a generated CycloneDX Component model accepts."""
    return {field.alias or name for name, field in model.model_fields.items()}


@lru_cache(maxsize=1)
def _fields_added_after_1_6() -> frozenset[str]:
    """Component keys 1.7 accepts and 1.6 forbids.

    Derived from the generated models rather than listed by hand: a later spec
    bump adds its new fields here without anyone remembering to, which is the
    failure mode that would otherwise ship an invalid download quietly.
    """
    from sbomify.apps.sboms.sbom_format_schemas import cyclonedx_1_6, cyclonedx_1_7

    return frozenset(_component_keys(cyclonedx_1_7.Component) - _component_keys(cyclonedx_1_6.Component))


def _document_from_hbom_sbom(hbom: Any) -> dict[str, Any] | None:
    """Load an HBOM SBOM row's document from S3. ``None`` when absent or unreadable."""
    from botocore.exceptions import BotoCoreError, ClientError

    from sbomify.apps.core.object_store import S3Client

    if hbom is None or not hbom.sbom_filename:
        return None
    try:
        raw = S3Client("SBOMS").get_sbom_data(hbom.sbom_filename)
    except (ClientError, BotoCoreError) as exc:
        # A missing/unreadable object must not 500 the merge — skip this HBOM, but
        # log so a genuinely misconfigured/unreachable bucket stays diagnosable.
        logger.warning("Could not load HBOM artifact %s from S3: %s", hbom.sbom_filename, exc)
        return None
    if not raw:
        return None
    try:
        document = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return document if isinstance(document, dict) else None


def build_release_hbom(release: Any, spec_version: str = "1.6") -> dict[str, Any] | None:
    """Merge the HBOM pinned in each component's release slot into one CycloneDX document.

    Only HBOM artifacts actually in the release (newest per component) are merged, so a component
    added to the product later never bleeds into an old release. Returns ``None`` when the release
    holds no HBOM. ``spec_version`` is the emitted ``specVersion`` ("1.6" default, "1.7").
    """
    from django.utils import timezone

    from sbomify.apps.core.models import ReleaseArtifact
    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.sboms.utils import _HARDWARE_TYPES

    # Only when down-levelling; emitting 1.7 keeps every key the member carried.
    downlevel_keys = _fields_added_after_1_6() if spec_version == "1.6" else frozenset()

    components: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    dep_by_ref: dict[str, dict[str, Any]] = {}  # merge dependsOn for a shared source ref
    seen_components: set[Any] = set()
    found = False
    artifacts = (
        ReleaseArtifact.objects.filter(release=release, sbom__bom_type=SBOM.BomType.HBOM)
        .select_related("sbom")
        # Newest by the pin itself, not by upload time: a release that
        # deliberately pins an older HBOM after a newer upload exists must
        # merge what it pinned. id breaks a same-instant tie one way.
        .order_by("sbom__component_id", "-created_at", "-id")
    )
    for artifact in artifacts:
        hbom_sbom = artifact.sbom
        if hbom_sbom is None or hbom_sbom.component_id in seen_components:
            continue
        seen_components.add(hbom_sbom.component_id)
        document = _document_from_hbom_sbom(hbom_sbom)
        if document is None:
            continue
        found = True
        # An HBOM names the board/device it describes in metadata.component and
        # hangs the parts off it (the upstream CycloneDX example does exactly
        # this), so the merged inventory must carry the device itself — dropping
        # it would leave a bag of connectors and dangle any edge rooted at it.
        source_components = list(document.get("components") or [])
        document_metadata = document.get("metadata")
        meta_component = document_metadata.get("component") if isinstance(document_metadata, dict) else None
        # Any hardware root, not only ``device``. _is_hbom accepts the whole
        # hardware set, so a board rooted at a ``platform`` is a legitimate HBOM
        # and its edges hang off that root; skipping the lift would leave those
        # edges naming a component the merged document does not contain, and a
        # consumer resolving them synthesises a phantom node.
        if isinstance(meta_component, dict) and meta_component.get("type") in _HARDWARE_TYPES:
            source_components.append(meta_component)

        # bom-ref is unique within a BOM, not across BOMs — CycloneDX scopes it
        # to the document. Two boards from one generator routinely both number
        # their parts from "1". Deduplicating on the bare string across members
        # therefore drops the second board's parts and reparents its dependency
        # edges onto the first board's node, so a release would silently ship an
        # inventory missing a whole board. Refs that collide with an earlier
        # member are re-keyed here and every edge in this document is rewritten
        # through the same map below. The first member keeps its refs unchanged,
        # which leaves the common single-HBOM download byte-comparable.
        remap: dict[str, str] = {}
        local_refs: set[str] = set()
        for comp in source_components:
            if not isinstance(comp, dict):
                continue
            if downlevel_keys:
                present = downlevel_keys.intersection(comp)
                if present:
                    comp = {k: v for k, v in comp.items() if k not in downlevel_keys}
                    logger.debug(
                        "[HBOM_MERGE] dropped %s from component in sbom_id=%s emitting %s",
                        sorted(present),
                        hbom_sbom.id,
                        spec_version,
                    )
            ref = comp.get("bom-ref")
            # Only dedupe on a real string bom-ref; a malformed non-string ref is
            # unhashable and can't be a dedup key, so keep the component as-is.
            if isinstance(ref, str) and ref:
                # A repeat inside one document is a genuine duplicate entry and
                # still collapses; only a repeat across documents is a collision.
                if ref in local_refs:
                    continue
                local_refs.add(ref)
                if ref in seen_refs:
                    candidate = f"{hbom_sbom.id}:{ref}"
                    suffix = 2
                    while candidate in seen_refs:
                        candidate = f"{hbom_sbom.id}-{suffix}:{ref}"
                        suffix += 1
                    remap[ref] = candidate
                    comp = {**comp, "bom-ref": candidate}
                    ref = candidate
                seen_refs.add(ref)
            components.append(comp)
        for dep in document.get("dependencies") or []:
            if not isinstance(dep, dict):
                continue
            ref = dep.get("ref")
            if not isinstance(ref, str) or not ref:
                continue
            ref = remap.get(ref, ref)
            # A dependsOn entry is normatively a list of bom-ref strings; tolerate a
            # malformed HBOM by keeping only the string targets rather than raising
            # (a non-list dependsOn contributes nothing).
            raw_targets = dep.get("dependsOn")
            targets = (
                [remap.get(t, t) for t in raw_targets if isinstance(t, str)] if isinstance(raw_targets, list) else []
            )
            existing = dep_by_ref.get(ref)
            if existing is None:
                # Copy so merging into it never mutates the source document.
                new_dep = {**dep, "ref": ref, "dependsOn": list(targets)}
                dep_by_ref[ref] = new_dep
                dependencies.append(new_dep)
            else:
                # Same source node in two HBOMs: union the targets rather than
                # dropping the second edge (which would hide a part of the assembly).
                have = set(existing["dependsOn"])
                for target in targets:
                    if target not in have:
                        have.add(target)
                        existing["dependsOn"].append(target)

    if not found:
        return None

    return {
        "bomFormat": "CycloneDX",
        "specVersion": spec_version,
        "serialNumber": "urn:uuid:" + str(uuid.uuid4()),
        "version": 1,
        "metadata": {
            "timestamp": timezone.now().isoformat(),
            "component": {
                "type": "application",
                "name": f"{release.product.name} {release.name}",
                "bom-ref": f"release-{release.id}",
            },
        },
        "components": components,
        "dependencies": dependencies,
    }
