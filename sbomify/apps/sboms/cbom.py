"""Merge a release's CBOM (Cryptography BOM) artifacts into one document.

A release can pin a CBOM per component. Consumers of the Trust Center want a
single crypto BOM for the release, so this unions the cryptographic-asset
components (and their dependency edges) of the newest CBOM in each component's
release slot into one CycloneDX document — the same shape as the merged VEX
download.

Member CBOMs may span lineages (legacy IBM 1.0, 1.6, 1.7). The merge emits 1.6
by default for consumer compatibility — 1.7-only vocabulary is down-converted
(``ellipticCurve`` -> ``curve``) or dropped with a log line
(``algorithmFamily``, ``relatedCryptographicAssets``) — and native 1.7 on
request. Legacy spellings always lift to the 1.6 shape, whichever the target.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from functools import cache
from typing import Any

from sbomify.apps.sboms.crypto_inventory import is_crypto_asset

logger = logging.getLogger(__name__)


def _document_from_cbom_sbom(cbom: Any) -> dict[str, Any] | None:
    """Load a CBOM SBOM row's document from S3. ``None`` when absent or unreadable."""
    from botocore.exceptions import BotoCoreError, ClientError

    from sbomify.apps.core.object_store import S3Client

    if cbom is None or not cbom.sbom_filename:
        return None
    try:
        raw = S3Client("SBOMS").get_sbom_data(cbom.sbom_filename)
    except (ClientError, BotoCoreError) as exc:
        # A missing/unreadable object must not 500 the merge — skip this CBOM, but
        # log so a genuinely misconfigured/unreachable bucket stays diagnosable.
        logger.warning("Could not load CBOM artifact %s from S3: %s", cbom.sbom_filename, exc)
        return None
    if not raw:
        return None
    try:
        document = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return document if isinstance(document, dict) else None


@cache
def _crypto_enum_tables() -> dict[str, dict[str, str]]:
    """Canonical-form -> spec-value tables for the crypto enums whose spellings
    changed across lineages (IBM 1.0 used camelCase: ``softwarePlainRam``,
    ``relatedCryptoMaterial``; 1.6+ uses kebab-case). Built from the 1.6
    schema module; 1.7 keeps the same values for these fields."""
    from sbomify.apps.sboms.sbom_format_schemas import cyclonedx_1_6 as cdx16

    def table(enum_cls: Any) -> dict[str, str]:
        return {re.sub(r"[^a-z0-9]", "", member.value.lower()): member.value for member in enum_cls}

    return {
        "assetType": table(cdx16.AssetType),
        "executionEnvironment": table(cdx16.ExecutionEnvironment),
        "implementationPlatform": table(cdx16.ImplementationPlatform),
        "primitive": table(cdx16.Primitive),
    }


def _align_enum_value(value: Any, allowed_by_canon: dict[str, str]) -> Any:
    if not isinstance(value, str):
        return value
    return allowed_by_canon.get(re.sub(r"[^a-z0-9]", "", value.lower()), value)


def _normalize_crypto_component(comp: dict[str, Any], spec_version: str) -> dict[str, Any]:
    """Copy of a crypto component conformant to the target spec version.

    Legacy IBM CBOM 1.0 spellings always lift to the 1.6 shape (``crypto-asset``
    type, ``variant``, ``implementationLevel``, root-level security levels).
    A 1.6 target additionally down-converts 1.7-only vocabulary. Copies before
    mutating so the source document (possibly cached) is never rewritten.
    """
    from sbomify.apps.sboms.crypto_inventory import LEGACY_CRYPTO_ASSET_TYPE, is_crypto_asset

    if not is_crypto_asset(comp):
        return comp
    out = dict(comp)
    if out.get("type") == LEGACY_CRYPTO_ASSET_TYPE:
        out["type"] = "cryptographic-asset"
    crypto = out.get("cryptoProperties")
    if not isinstance(crypto, dict):
        return out
    crypto = dict(crypto)
    out["cryptoProperties"] = crypto
    algo = crypto.get("algorithmProperties")
    algo = dict(algo) if isinstance(algo, dict) else None
    if algo is not None:
        crypto["algorithmProperties"] = algo
        if "variant" in algo:
            algo.setdefault("parameterSetIdentifier", algo.pop("variant"))
        if "implementationLevel" in algo:
            algo.setdefault("executionEnvironment", algo.pop("implementationLevel"))
        if isinstance(algo.get("certificationLevel"), str):
            algo["certificationLevel"] = [algo["certificationLevel"]]
    for key in ("classicalSecurityLevel", "nistQuantumSecurityLevel"):
        # 1.6 moved these from the cryptoProperties root into algorithmProperties.
        if key in crypto:
            value = crypto.pop(key)
            if algo is None:
                algo = {}
                crypto["algorithmProperties"] = algo
            algo.setdefault(key, value)
    # Enum spellings changed across lineages too (softwarePlainRam ->
    # software-plain-ram, relatedCryptoMaterial -> related-crypto-material);
    # align known values onto the spec vocabulary, leave unknown ones as-is.
    tables = _crypto_enum_tables()
    if "assetType" in crypto:
        crypto["assetType"] = _align_enum_value(crypto["assetType"], tables["assetType"])
    if algo is not None:
        for key in ("executionEnvironment", "implementationPlatform", "primitive"):
            if key in algo:
                algo[key] = _align_enum_value(algo[key], tables[key])
    if spec_version == "1.6":
        if algo is not None and "ellipticCurve" in algo:
            algo.setdefault("curve", algo.pop("ellipticCurve"))
        if algo is not None and "algorithmFamily" in algo:
            dropped = algo.pop("algorithmFamily")
            logger.info("Release CBOM merge: dropped 1.7-only algorithmFamily=%r for 1.6 output", dropped)
        # 1.7 nests relatedCryptographicAssets inside each sub-object, next to
        # the deprecated 1.6 ref fields (which stay — they are 1.6 vocabulary).
        for key in ("certificateProperties", "relatedCryptoMaterialProperties", "protocolProperties"):
            sub = crypto.get(key)
            if isinstance(sub, dict) and "relatedCryptographicAssets" in sub:
                sub = dict(sub)
                sub.pop("relatedCryptographicAssets")
                crypto[key] = sub
                logger.info("Release CBOM merge: dropped 1.7-only %s.relatedCryptographicAssets for 1.6 output", key)
    return out


def build_release_cbom(release: Any, spec_version: str = "1.6") -> dict[str, Any] | None:
    """Merge the CBOM pinned in each component's release slot into one CycloneDX document.

    Only CBOM artifacts actually in the release (newest per component) are merged, so a component
    added to the product later never bleeds into an old release. Returns ``None`` when the release
    holds no CBOM. ``spec_version`` selects the output vocabulary ("1.6" default, "1.7" native).
    """
    from django.utils import timezone

    from sbomify.apps.core.models import ReleaseArtifact
    from sbomify.apps.sboms.models import SBOM

    components: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    dep_by_ref: dict[str, dict[str, Any]] = {}  # merge dependsOn for a shared source ref
    seen_components: set[Any] = set()
    found = False
    artifacts = (
        ReleaseArtifact.objects.filter(release=release, sbom__bom_type=SBOM.BomType.CBOM)
        .select_related("sbom")
        .order_by("sbom__component_id", "-sbom__created_at")
    )
    for artifact in artifacts:
        cbom_sbom = artifact.sbom
        if cbom_sbom is None or cbom_sbom.component_id in seen_components:
            continue
        seen_components.add(cbom_sbom.component_id)
        document = _document_from_cbom_sbom(cbom_sbom)
        if document is None:
            continue
        found = True
        # Mirror derive_crypto_inventory: a pure CBOM may carry its sole
        # crypto asset in metadata.component, and the merged deliverable must
        # not drop it.
        source_components = list(document.get("components") or [])
        document_metadata = document.get("metadata")
        meta_component = document_metadata.get("component") if isinstance(document_metadata, dict) else None
        if is_crypto_asset(meta_component):
            source_components.append(meta_component)
        for comp in source_components:
            if not isinstance(comp, dict):
                continue
            ref = comp.get("bom-ref")
            # Only dedupe on a real string bom-ref; a malformed non-string ref is
            # unhashable and can't be a dedup key, so keep the component as-is.
            if isinstance(ref, str) and ref:
                if ref in seen_refs:
                    continue
                seen_refs.add(ref)
            components.append(_normalize_crypto_component(comp, spec_version))
        for dep in document.get("dependencies") or []:
            if not isinstance(dep, dict):
                continue
            ref = dep.get("ref")
            if not isinstance(ref, str) or not ref:
                continue
            # A dependsOn entry is normatively a list of bom-ref strings; tolerate a
            # malformed CBOM by keeping only the string targets rather than raising
            # (a non-list dependsOn contributes nothing).
            raw_targets = dep.get("dependsOn")
            targets = [t for t in raw_targets if isinstance(t, str)] if isinstance(raw_targets, list) else []
            existing = dep_by_ref.get(ref)
            if existing is None:
                # Copy so merging into it never mutates the source document.
                new_dep = {**dep, "dependsOn": list(targets)}
                dep_by_ref[ref] = new_dep
                dependencies.append(new_dep)
            else:
                # Same source node in two CBOMs: union the targets rather than
                # dropping the second edge (which would hide crypto usage).
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
