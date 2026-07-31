from __future__ import annotations

import json
import logging
import re
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.db import transaction
from django.http import HttpRequest

from sbomify.apps.core.authz import can
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.core.utils import broadcast_to_workspace
from sbomify.apps.sboms.crypto_inventory import CryptoAsset, derive_crypto_inventory
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.pqc import assess_inventory, replacement_for

log = logging.getLogger(__name__)


def schedule_vex_reapply(component_id: str) -> None:
    """Enqueue the VEX re-apply to run after the current transaction commits (async, best-effort).

    ``transaction.on_commit`` guarantees the VEX row change is visible to the worker; enqueuing (a
    Redis push) is cheap, and any broker error is swallowed so the triggering request still
    succeeds.
    """

    def _send() -> None:
        try:
            from sbomify.apps.vulnerability_scanning.tasks import reapply_vex_to_component_scans

            reapply_vex_to_component_scans.send(component_id)
        except Exception:
            log.warning("Failed to enqueue VEX re-apply for component %s", component_id, exc_info=True)

    transaction.on_commit(_send)


def delete_sbom_record(request: HttpRequest, sbom_id: str) -> ServiceResult[None]:
    try:
        sbom = SBOM.objects.select_related("component__team").get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return ServiceResult.failure("SBOM not found", status_code=404)

    if not can(request, "sbom:delete", sbom.component):
        return ServiceResult.failure("Only owners of the component can delete SBOMs", status_code=403)

    # Capture info for broadcast before deleting
    workspace_key = sbom.component.team.key
    component_id = str(sbom.component.id)
    sbom_name = sbom.name
    was_vex = sbom.bom_type == SBOM.BomType.VEX.value
    bom_type = sbom.bom_type
    source = sbom.source or ""

    s3 = S3Client("SBOMS")
    for blob_key in filter(None, [sbom.sbom_filename, sbom.signature_blob_key, sbom.provenance_blob_key]):
        try:
            s3.delete_object(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, blob_key)
        except Exception as exc:
            log.warning("Failed to delete S3 object %s: %s", blob_key, exc)

    sbom.delete()

    from sbomify.apps.core.analytics import events
    from sbomify.apps.core.posthog_service import capture_for_request

    # Defer the analytics event to commit: if the delete rolls back (this can run
    # inside a caller's transaction), an eager capture would record an
    # irreversible *:deleted for a delete that never happened. Matches the
    # broadcast below.
    deleted_event = {
        "vex": events.VEX_DELETED,
        "cbom": events.CBOM_DELETED,
        "hbom": events.HBOM_DELETED,
    }.get(bom_type, events.SBOM_DELETED)
    transaction.on_commit(
        lambda: capture_for_request(
            request,
            deleted_event,
            {"component_id": component_id, "sbom_id": sbom_id, "source": source},
            team_key=workspace_key or "",
        )
    )

    # Deleting a VEX retracts its statements: re-annotate the component's stored
    # scans so the suppressed findings surface again.
    if was_vex:
        schedule_vex_reapply(component_id)

    # Broadcast to workspace for real-time UI updates (after transaction commits)
    if workspace_key:
        _workspace_key = workspace_key
        transaction.on_commit(
            lambda: broadcast_to_workspace(
                workspace_key=_workspace_key,
                message_type="sbom_deleted",
                data={"sbom_id": sbom_id, "component_id": component_id, "name": sbom_name},
            )
        )

    return ServiceResult.success()


def serialize_sbom(sbom: SBOM) -> dict[str, Any]:
    return {
        "id": str(sbom.id),
        "name": sbom.name,
        "version": sbom.version,
        "format": sbom.format,
        "format_version": sbom.format_version,
        "sbom_filename": sbom.sbom_filename,
        "created_at": sbom.created_at,
        "source": sbom.source,
        "component_id": str(sbom.component.id),
        "component_name": sbom.component.name,
        "source_display": sbom.source_display,
        "bom_type": sbom.bom_type,
        "signature_blob_key": sbom.signature_blob_key,
        "signature_type": sbom.signature_type,
        "provenance_blob_key": sbom.provenance_blob_key,
    }


def get_sbom_detail(request: HttpRequest, sbom_id: str) -> ServiceResult[dict[str, Any]]:
    try:
        sbom = SBOM.objects.select_related("component").get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return ServiceResult.failure("SBOM not found", status_code=404)

    component = sbom.component

    # Route through the authz front door so a scoped API token's read scope is
    # honoured — check_component_access alone enforces visibility/NDA but not the
    # token action-scope (that gate lives in can()). component:access is the ABAC
    # read action; no change for sessions, anonymous callers, or full/read-only
    # tokens, only non-read-scoped tokens are newly denied.
    from sbomify.apps.core.authz import can

    if not can(request, "component:access", component):
        return ServiceResult.failure("Forbidden", status_code=403)

    return ServiceResult.success(serialize_sbom(sbom))


_WEAK_SUITE_TOKENS = {
    "NULL": "no encryption or integrity",
    "ANON": "anonymous key exchange (no authentication)",
    "ADH": "anonymous key exchange (no authentication)",
    "AECDH": "anonymous key exchange (no authentication)",
    "EXPORT": "export-grade key sizes",
    "EXPORT40": "export-grade key sizes",
    "EXPORT1024": "export-grade key sizes",
    "RC4": "RC4 (prohibited by RFC 7465)",
    "DES": "single DES (56-bit key)",
    "3DES": "3DES (Sweet32; withdrawn)",
    "EDE": "3DES (Sweet32; withdrawn)",
    "MD5": "MD5 MAC (broken)",
}


def _suite_weaknesses(name: str) -> list[str]:
    tokens = set(re.split(r"[^A-Z0-9]+", name.upper()))
    return sorted({reason for token, reason in _WEAK_SUITE_TOKENS.items() if token in tokens})


def _certificate_view(cert: dict[str, Any] | None) -> dict[str, Any] | None:
    """Interpreted certificate fields: validity window, expiry countdown, lifecycle states."""
    if not isinstance(cert, dict):
        return None
    from django.utils import timezone as django_timezone

    from sbomify.apps.sboms.crypto_inventory import cert_expiry_state

    days, expired, expiring_soon = cert_expiry_state(cert.get("notValidAfter"), django_timezone.now())
    states: list[str] = []
    raw_state = cert.get("certificateState")
    for item in raw_state if isinstance(raw_state, list) else [raw_state]:
        if isinstance(item, dict):
            state = item.get("state") or item.get("name")
            if isinstance(state, str):
                states.append(state)
        elif isinstance(item, str):
            states.append(item)
    return {
        "subject": cert.get("subjectName"),
        "issuer": cert.get("issuerName"),
        "serial": cert.get("serialNumber"),
        "not_before": cert.get("notValidBefore"),
        "not_after": cert.get("notValidAfter"),
        "states": states,
        "days_to_expiry": days,
        "expired": expired,
        "expiring_soon": expiring_soon,
    }


def _protocol_view(proto: dict[str, Any] | None) -> dict[str, Any] | None:
    """Interpreted protocol fields: version deprecation and enumerated cipher suites."""
    if not isinstance(proto, dict):
        return None
    ptype = proto.get("type") if isinstance(proto.get("type"), str) else None
    version = str(proto.get("version")) if proto.get("version") is not None else None
    weak_version = None
    bare = (version or "").lstrip("vV")
    if ptype and ptype.lower().startswith("ssl"):
        weak_version = "SSL is deprecated (RFC 7568)"
    elif ptype and ptype.lower() == "tls" and bare in ("1.0", "1.1"):
        weak_version = "TLS 1.0/1.1 are deprecated (RFC 8996)"
    suites: list[dict[str, Any]] = []
    raw = proto.get("cipherSuites")
    legacy = proto.get("tlsCipherSuites")  # IBM CBOM 1.0 spelling
    for entry in (raw if isinstance(raw, list) else []) + (legacy if isinstance(legacy, list) else []):
        if isinstance(entry, dict):
            name = entry.get("name") if isinstance(entry.get("name"), str) else None
            identifiers = [i for i in (entry.get("identifiers") or []) if isinstance(i, str)]
        elif isinstance(entry, str):
            name, identifiers = entry, []
        else:
            continue
        suites.append({"name": name, "identifiers": identifiers, "weaknesses": _suite_weaknesses(name) if name else []})
    return {"type": ptype, "version": version, "weak_version": weak_version, "cipher_suites": suites}


def _serialize_crypto_asset(asset: CryptoAsset) -> dict[str, Any]:
    return {
        "name": asset.name,
        "bom_ref": asset.bom_ref,
        "oid": asset.oid,
        "asset_type": asset.asset_type,
        "primitive": asset.primitive,
        "algorithm_family": asset.algorithm_family,
        "parameter_set": asset.parameter_set,
        "curve": asset.curve,
        "nist_quantum_security_level": asset.nist_quantum_security_level,
        "classical_security_level": asset.classical_security_level,
        "crypto_functions": list(asset.crypto_functions),
        "mode": asset.mode,
        "padding": asset.padding,
        "execution_environment": asset.execution_environment,
        "implementation_platform": asset.implementation_platform,
        "certification_level": list(asset.certification_level),
        "normalized_family": asset.normalized_family,
        "normalized_curve": asset.normalized_curve,
        "registry_unrecognized": asset.registry_unrecognized,
        "certificate": asset.certificate,
        "protocol": asset.protocol,
        "related_material": asset.related_material,
        "certificate_view": _certificate_view(asset.certificate),
        "protocol_view": _protocol_view(asset.protocol),
    }


def get_crypto_inventory(request: HttpRequest, sbom_id: str) -> ServiceResult[dict[str, Any]]:
    """Derive the cryptographic-asset (CBOM) inventory for an SBOM.

    Reads the immutable artifact from storage and projects its
    ``cryptographic-asset`` components (ADR-004 — nothing is persisted or
    mutated). Returns an empty inventory when the artifact carries no crypto
    assets or is not a parseable CycloneDX document.
    """
    try:
        sbom = SBOM.objects.select_related("component", "component__team").get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return ServiceResult.failure("SBOM not found", status_code=404)

    # Route through can() so a scoped API token's read scope is honoured (this
    # endpoint runs optional_auth, so a PAT reaches it). component:access is the
    # ABAC read action; no change for sessions / full / read-only tokens.
    from sbomify.apps.core.authz import can

    if not can(request, "component:access", sbom.component):
        return ServiceResult.failure("Forbidden", status_code=403)

    if not sbom.sbom_filename:
        return ServiceResult.failure("SBOM file not found", status_code=404)

    # The artifact is immutable (ADR-004), so the derived inventory is a pure
    # function of the SBOM id: cache it after the per-request access check.
    # Only the certificate expiry countdown is time-sensitive, and at day
    # granularity a bounded TTL cannot change it. Bump the version key when
    # the derivation shape changes.
    from django.core.cache import cache as django_cache

    cache_key = f"crypto-inventory:v1:{sbom.id}"
    cached = django_cache.get(cache_key)
    if cached is not None:
        return ServiceResult.success(cached)

    try:
        raw = S3Client("SBOMS").get_sbom_data(sbom.sbom_filename)
    except (BotoCoreError, ClientError) as exc:
        # The posture card is best-effort and lazy-loaded after page render
        # (ComponentCryptoPostureView / SbomCryptoInventoryView): ANY storage
        # failure must collapse it, never 500 — a 500 reintroduces the
        # nondeterministic HTMX error toast and degrades the page on a transient
        # outage. A genuinely missing object is "not found" (same as the SBOM
        # download path); everything else — unreachable store, NoSuchBucket,
        # AccessDenied, bad credentials — is reported as temporarily unavailable.
        code = exc.response.get("Error", {}).get("Code") if isinstance(exc, ClientError) else None
        if code in ("NoSuchKey", "404"):
            return ServiceResult.failure("SBOM file not found", status_code=404)
        log.warning(
            "Crypto inventory: object store error (%s) for SBOM %s", code or "connection", sbom_id, exc_info=True
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

    inventory = derive_crypto_inventory(document if isinstance(document, dict) else None)
    summary = assess_inventory(inventory)
    payload = {
        "sbom_id": str(sbom.id),
        "component_id": str(sbom.component.id),
        "count": inventory.count,
        "by_asset_type": inventory.by_asset_type,
        "edges": [
            {"source": e.source, "relation": e.relation, "target": e.target, "resolved": e.resolved}
            for e in inventory.edges
        ],
        "pqc_overall": summary.overall,
        "pqc_counts": summary.counts,
        "assets": [
            {
                **_serialize_crypto_asset(result.asset),
                "pqc_status": result.assessment.status.value,
                "pqc_reason": result.assessment.reason,
                "pqc_data_quality_flag": result.assessment.data_quality_flag,
                "pqc_replacement": replacement_for(result.asset, result.assessment.status),
            }
            for result in summary.results
        ],
    }
    django_cache.set(cache_key, payload, 3600)
    return ServiceResult.success(payload)
