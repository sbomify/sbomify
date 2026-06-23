from __future__ import annotations

import json
import logging
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
from sbomify.apps.sboms.pqc import assess_inventory

log = logging.getLogger(__name__)


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

    s3 = S3Client("SBOMS")
    for blob_key in filter(None, [sbom.sbom_filename, sbom.signature_blob_key, sbom.provenance_blob_key]):
        try:
            s3.delete_object(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, blob_key)
        except Exception as exc:
            log.warning("Failed to delete S3 object %s: %s", blob_key, exc)

    sbom.delete()

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
        "certificate": asset.certificate,
        "protocol": asset.protocol,
        "related_material": asset.related_material,
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
    return ServiceResult.success(
        {
            "sbom_id": str(sbom.id),
            "component_id": str(sbom.component.id),
            "count": inventory.count,
            "by_asset_type": inventory.by_asset_type,
            "pqc_overall": summary.overall,
            "pqc_counts": summary.counts,
            "assets": [
                {
                    **_serialize_crypto_asset(result.asset),
                    "pqc_status": result.assessment.status.value,
                    "pqc_reason": result.assessment.reason,
                    "pqc_data_quality_flag": result.assessment.data_quality_flag,
                }
                for result in summary.results
            ],
        }
    )
