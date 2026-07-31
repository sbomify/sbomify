from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Any

from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from ninja import File, Query, Router, UploadedFile
from ninja.decorators import decorate_view
from ninja.security import django_auth
from pydantic import ValidationError

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth, optional_auth
from sbomify.apps.access_tokens.throttling import AccessTokenHeavyRateThrottle, AccessTokenRateThrottle
from sbomify.apps.core.apis import get_component_metadata, patch_component_metadata
from sbomify.apps.core.authz import can
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.core.purl import extract_purl_qualifiers
from sbomify.apps.core.schemas import ErrorCode, ErrorResponse
from sbomify.apps.core.services.access_control import check_component_access, check_component_access_for_user
from sbomify.apps.core.utils import (
    ExtractSpec,
    broadcast_to_workspace,
    build_entity_info_dict,
    dict_update,
    get_by_uuid_or_pk,
    obj_extract,
)
from sbomify.apps.oidc.permissions import is_authorised_for_component
from sbomify.apps.sboms.utils import (
    _contains_crypto_assets,
    _is_cbom,
    _is_duplicate_integrity_error,
    verify_download_token,
)
from sbomify.apps.teams.models import ContactProfile

from .models import SBOM, Component, Product
from .schemas import (
    ComponentMetaData,
    CryptoInventorySchema,
    CycloneDXSupportedVersion,
    SBOMResponseSchema,
    SBOMUploadRequest,
    SPDX3Package,
    SPDX3Schema,
    SPDXPackage,
    SPDXSchema,
    SupplierSchema,
    cdx13,
    cdx14,
    cdx15,
    cdx16,
    cdx17,
    validate_cyclonedx_sbom,
    validate_spdx_sbom,
)
from .services.sboms import delete_sbom_record, get_crypto_inventory, get_sbom_detail, schedule_vex_reapply

log = logging.getLogger(__name__)

# Max SBOM upload size in bytes (100MB — SPDX 3.0 SBOMs can be 50-100MB)
SBOM_MAX_UPLOAD_SIZE = 100 * 1024 * 1024


_VALID_BOM_TYPES = {choice[0] for choice in SBOM.BomType.choices}


def _validate_bom_type(bom_type: str) -> tuple[int, dict[str, Any]] | None:
    """Validate bom_type against BomType enum. Returns error response tuple or None if valid."""
    if bom_type not in _VALID_BOM_TYPES:
        return 400, {
            "detail": f"Invalid bom_type '{bom_type}'. Must be one of: {', '.join(sorted(_VALID_BOM_TYPES))}",
            "error_code": ErrorCode.VALIDATION_ERROR,
        }
    return None


def _store_external_vex(
    component: Component,
    document: dict[str, Any],
    file_content: bytes,
    sha256_hash: str,
    vex_format: str,
    source: str,
) -> tuple[int, dict[str, Any]]:
    """Store a non-JSON-CycloneDX VEX document as a ``bom_type=vex`` artifact.

    Handles OpenVEX, CSAF, and CycloneDX *XML* (all routed here because their
    bytes cannot round-trip the JSON CycloneDX schema validation).

    The raw bytes are stored unmodified (ADR-004); only the identifying
    metadata is read out. Like CycloneDX VEX, no duplicate check applies —
    VEX documents are re-issued continuously and the latest wins by
    ``created_at``.
    """
    from sbomify.apps.vulnerability_scanning.vex_formats import (
        VEX_FORMAT_CSAF,
        VEX_FORMAT_OPENVEX,
        openvex_context,
    )

    if vex_format == VEX_FORMAT_OPENVEX:
        context = openvex_context(document) or ""
        _, separator, suffix = context.rpartition("/ns/")
        # v0.0.1 documents use the bare namespace with no version suffix.
        format_version = suffix if separator else "v0.0.1"
        raw_version = document.get("version")
    elif vex_format == VEX_FORMAT_CSAF:
        raw_meta = document.get("document")
        meta = raw_meta if isinstance(raw_meta, dict) else {}
        format_version = str(meta.get("csaf_version") or "")
        tracking = meta.get("tracking")
        raw_version = tracking.get("version") if isinstance(tracking, dict) else None
    else:
        # CycloneDX delivered as XML: stored verbatim like the other external
        # formats — the partial XML-to-dict conversion cannot round-trip the
        # JSON schema validation the JSON path applies.
        format_version = str(document.get("specVersion") or "")
        raw_version = document.get("version")
    # Explicit None-check: a falsy-but-present version (e.g. 0) is still a version.
    version = "" if raw_version is None else str(raw_version)

    s3 = S3Client("SBOMS")
    filename = s3.upload_sbom(file_content)

    sbom = SBOM(
        name=component.name,
        component=component,
        format=vex_format,
        format_version=format_version[:20],
        version=version,
        source=source,
        sbom_filename=filename,
        sha256_hash=sha256_hash,
        bom_type=SBOM.BomType.VEX.value,
    )
    try:
        with transaction.atomic():
            sbom.save()
    except IntegrityError:
        _cleanup_orphaned_s3_object(filename)
        raise

    # The row is committed; a broadcast hiccup must not fail the upload.
    try:
        _broadcast_sbom_uploaded(component, sbom)
    except Exception:
        log.warning("Failed to broadcast SBOM upload notification", exc_info=True)
    schedule_vex_reapply(component.id)
    return 201, {"id": sbom.id}


def _cleanup_orphaned_s3_object(filename: str) -> None:
    """Log a potential orphaned S3 object for manual cleanup.

    Under READ COMMITTED isolation, a synchronous .exists() check can race
    with concurrent transactions, risking deletion of objects still needed.
    Instead of immediate deletion, we log at WARNING level so operators can
    monitor and clean up orphans manually or via future automation.
    """
    log.warning("Potential orphaned S3 object after IntegrityError: %s", filename)


router = Router(tags=["Artifacts"], auth=(PersonalAccessTokenAuth(), django_auth))


def _broadcast_sbom_uploaded(component: Component, sbom: SBOM) -> None:
    """Broadcast SBOM upload notification to workspace members."""
    broadcast_to_workspace(
        workspace_key=component.team.key or "",
        message_type="sbom_uploaded",
        data={"sbom_id": str(sbom.id), "component_id": str(component.id), "name": sbom.name},
    )


item_type_map = {"component": Component, "product": Product}


def _build_component_metadata_from_native_fields(component: Component) -> ComponentMetaData:
    """Build ComponentMetaData from component's native fields and contact profile.

    This mirrors the logic in core.apis.get_component_metadata() to build metadata
    from the component's native fields (supplier, authors, licenses, etc.) and
    contact profile entities (manufacturer, supplier).
    """
    # Build supplier and manufacturer from contact profile
    supplier: dict[str, Any] = {"contacts": []}
    manufacturer: dict[str, Any] = {"contacts": []}

    if component.contact_profile:
        profile = component.contact_profile
        # Ensure profile is prefetched with entities and contacts
        if not hasattr(profile, "_prefetched_objects_cache"):
            profile = ContactProfile.objects.prefetch_related("entities", "entities__contacts").get(pk=profile.pk)

        # Find supplier and manufacturer entities
        supplier_entity = None
        manufacturer_entity = None
        for entity in profile.entities.all():
            if entity.is_supplier and supplier_entity is None:
                supplier_entity = entity
            if entity.is_manufacturer and manufacturer_entity is None:
                manufacturer_entity = entity

        # Build supplier and manufacturer using shared utility
        supplier = build_entity_info_dict(supplier_entity)
        manufacturer = build_entity_info_dict(manufacturer_entity)
    else:
        # Fall back to component's native fields if no contact profile
        if component.supplier_name:
            supplier["name"] = component.supplier_name
        if component.supplier_url:
            supplier["url"] = component.supplier_url
        if component.supplier_address:
            supplier["address"] = component.supplier_address
        for contact in component.supplier_contacts.all():
            contact_dict = {"name": contact.name}
            if contact.email is not None:
                contact_dict["email"] = contact.email
            if contact.phone is not None:
                contact_dict["phone"] = contact.phone
            supplier["contacts"].append(contact_dict)

    # Build authors from native fields
    authors = []
    for author in component.authors.all():
        author_dict = {"name": author.name}
        if author.email is not None:
            author_dict["email"] = author.email
        if author.phone is not None:
            author_dict["phone"] = author.phone
        authors.append(author_dict)

    # Get licenses from native fields
    licenses = []
    for license_obj in component.licenses.all():
        licenses.append(license_obj.to_dict())

    return ComponentMetaData(
        id=component.id,
        name=component.name,
        supplier=SupplierSchema.model_validate(supplier),
        manufacturer=SupplierSchema.model_validate(manufacturer),
        authors=authors,  # type: ignore[arg-type]
        licenses=licenses,  # type: ignore[arg-type]
        lifecycle_phase=component.lifecycle_phase,
        contact_profile_id=component.contact_profile_id,
        contact_profile=None,  # Not needed for CycloneDX generation
        uses_custom_contact=component.contact_profile is None,
    )


def _extract_cdx_purl(payload: Any) -> str | None:
    """Extract PURL from a CycloneDX payload's metadata.component.purl."""
    try:
        purl = payload.metadata.component.purl
        return str(purl) if purl else None
    except AttributeError:
        return None


def _extract_spdx_primary_package(
    payload: SPDXSchema | SPDX3Schema,
) -> tuple[SPDXPackage | SPDX3Package, str] | tuple[None, str]:
    """Extract primary package from an SPDX payload.

    Dispatches to SPDX 2.x or 3.0 extraction logic based on payload type.

    Returns:
        Tuple of (package, "") on success, or (None, error_message) on failure.
    """
    if isinstance(payload, SPDX3Schema):
        return _extract_spdx3_primary_package(payload)
    return _extract_spdx2_primary_package(payload)


def _extract_spdx2_primary_package(
    payload: SPDXSchema,
) -> tuple[SPDXPackage, str] | tuple[None, str]:
    """Extract primary package from SPDX 2.x document.

    Strategy:
    1. Look for a package referenced by documentDescribes field
    2. Fall back to matching package name with document name
    """
    if not payload.packages:
        return None, "No packages found in SPDX document"

    package: SPDXPackage | None = None

    # First check if documentDescribes is present and points to a valid package
    if hasattr(payload, "documentDescribes") and payload.documentDescribes:
        described_ref: str = payload.documentDescribes[0]
        for pkg in payload.packages:
            if hasattr(pkg, "SPDXID") and pkg.SPDXID == described_ref:
                package = pkg
                break

    # If not found via documentDescribes, fall back to name matching
    if not package:
        for pkg in payload.packages:
            if pkg.name == payload.name:
                package = pkg
                break

    if not package:
        return None, f"No package found with name '{payload.name}' in SPDX document"

    return package, ""


def _extract_spdx3_primary_package(
    payload: SPDX3Schema,
) -> tuple[SPDX3Package, str] | tuple[None, str]:
    """Extract primary package from SPDX 3.0 document.

    Strategy:
    1. Find a 'describes' relationship and use its target package
    2. Fall back to matching package name with document name
    3. Fall back to first software_Package element
    """
    packages = payload.packages
    if not packages:
        return None, "No packages found in SPDX 3.0 document"

    package: SPDX3Package | None = None

    # Strategy 1: Find 'describes' relationship target
    for rel in payload.relationships:
        rel_type = rel.get("relationshipType", "")
        if rel_type == "describes":
            target_ids = rel.get("to", [])
            if target_ids:
                target_id = target_ids[0]
                for pkg in packages:
                    if pkg.spdx_id == target_id:
                        package = pkg
                        break
            if package:
                break

    # Strategy 2: Match by document name
    if not package and payload.name:
        for pkg in packages:
            if pkg.name == payload.name:
                package = pkg
                break

    # Strategy 3: Fall back to first package
    if not package:
        package = packages[0]

    return package, ""


# Removed duplicate component creation endpoint - use /api/v1/components instead


# Removed duplicate public_status endpoints - use core API PATCH endpoints with is_public field instead


def _public_api_item_access_checks(
    request: HttpRequest, item_type: str, item_id: str
) -> Component | Product | tuple[int, dict[str, str]]:
    if item_type not in item_type_map:
        return 400, {"detail": "Invalid item type"}

    model_class = item_type_map[item_type]

    rec: Component | Product = get_object_or_404(model_class, pk=item_id)  # type: ignore[assignment]

    if not can(request, f"{item_type}:manage", rec):  # item_type is validated to product|component above
        return 403, {"detail": "Forbidden"}

    return rec


@router.post(
    "/artifact/cyclonedx/{component_id}",
    response={201: SBOMUploadRequest, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 409: ErrorResponse},
    auth=PersonalAccessTokenAuth(),
    # Per-op throttle REPLACES the global, so pass both: keep the global per-token
    # limit AND the stricter heavy-upload limit (#1070).
    throttle=[AccessTokenRateThrottle(), AccessTokenHeavyRateThrottle()],
)
def sbom_upload_cyclonedx(
    request: HttpRequest,
    component_id: str,
    bom_type: str = "sbom",
) -> tuple[int, dict[str, Any]]:
    """
    Upload CycloneDX format BOM for a component.

    Supports multiple CycloneDX versions. The version is detected from the specVersion
    field in the BOM data, and the appropriate schema is used for validation.

    Args:
        component_id: The component to attach the BOM to.
        bom_type: BOM type classification (default: "sbom"). Accepted values are
            defined by ``SBOM.BomType`` (e.g., "sbom", "vex", "cbom", "hbom").
            Non-"sbom" types are only supported for CycloneDX uploads.

    To add support for a new CycloneDX version:
    1. Add the version to CycloneDXSupportedVersion enum in schemas.py
    2. Import the new schema module (e.g., cdx17)
    3. Add it to the module_map in get_cyclonedx_module()
    """
    if bom_type_error := _validate_bom_type(bom_type):
        return bom_type_error

    try:
        component = Component.objects.filter(id=component_id).first()
        if component is None:
            return 404, {"detail": "Component not found"}

        # Allow OIDC bot tokens for trusted-publishing uploads. The second
        # check enforces that the bot can only push to ITS bound component,
        # not anywhere else in the workspace — see
        # ``sbomify.apps.oidc.permissions.is_authorised_for_component``.
        if not can(request, "artifact:publish", component):
            return 403, {"detail": "Forbidden"}
        # A VEX rewrites the workspace's stored vulnerability posture, so it takes
        # the stricter publish tier (guests are excluded).
        if bom_type == SBOM.BomType.VEX.value and not can(request, "artifact:publish_vex", component):
            return 403, {"detail": "Forbidden"}
        if not is_authorised_for_component(request, component):
            return 403, {"detail": "Forbidden"}

        # Parse JSON from request body
        try:
            sbom_data = json.loads(request.body)
        except json.JSONDecodeError:
            return 400, {"detail": "Invalid JSON"}

        # Validate and get the appropriate schema version
        try:
            payload, spec_version = validate_cyclonedx_sbom(sbom_data)
        except ValueError as e:
            # Unsupported version
            return 400, {"detail": str(e)}
        except ValidationError as e:
            # Invalid format for the detected version
            spec_version = sbom_data.get("specVersion", "unknown")
            return 400, {"detail": f"Invalid CycloneDX {spec_version} format: {str(e)}"}

        # Compute SHA256 hash of the SBOM content
        sha256_hash = hashlib.sha256(request.body).hexdigest()

        sbom_dict = obj_extract(
            obj_in=payload,
            fields=[
                ExtractSpec("metadata.component.name", required=False, default="", rename_to="name"),
                ExtractSpec("metadata.component.version", required=False, rename_to="version"),
                ExtractSpec("specVersion", required=True, rename_to="format_version"),
            ],
        )

        # metadata.component is optional in CycloneDX; fall back to the sbomify Component name
        if not sbom_dict.get("name"):
            sbom_dict["name"] = component.name

        # Version if present is a Version class and needs to be converted to string.
        if "version" in sbom_dict and not isinstance(sbom_dict["version"], str):
            sbom_dict["version"] = sbom_dict["version"].model_dump(exclude_none=True)

        sbom_version = sbom_dict.get("version", "")
        sbom_format = "cyclonedx"

        # Auto-detect CBOM content: an action-published CBOM arrives with the
        # default bom_type; tag it cbom so the cbom-gated PQC plugin runs. Only
        # when the caller left the type as the default — an explicit bom_type
        # (e.g. the delegated /artifact/vex/ path passing "vex") is honored so
        # a crypto-heavy VEX is never re-tagged cbom.
        if bom_type == SBOM.BomType.SBOM.value and "bom_type" not in request.GET and _is_cbom(sbom_data):
            bom_type = "cbom"
        sbom_dict["has_crypto_assets"] = _contains_crypto_assets(sbom_data)

        # Extract PURL qualifiers from metadata.component.purl
        cdx_purl = _extract_cdx_purl(payload)
        sbom_qualifiers = extract_purl_qualifiers(cdx_purl) if cdx_purl else {}

        # VEX is re-issued continuously against the same release with no meaningful version, so it is
        # exempt from the duplicate guard (multiple rows coexist, the latest is by created_at). SBOM
        # and CBOM keep the guard so a re-uploaded static artifact stays a 409.
        if (
            bom_type != SBOM.BomType.VEX
            and SBOM.objects.filter(
                component=component,
                version=sbom_version,
                format=sbom_format,
                qualifiers=sbom_qualifiers,
                bom_type=bom_type,
            ).exists()
        ):
            return 409, {
                "detail": f"{bom_type.upper()} artifact with version '{sbom_version}' and format '{sbom_format}' "
                "already exists for this component",
                "error_code": ErrorCode.DUPLICATE_ARTIFACT,
            }

        s3 = S3Client("SBOMS")
        filename = s3.upload_sbom(request.body)

        sbom_dict["format"] = sbom_format
        sbom_dict["sbom_filename"] = filename
        sbom_dict["component"] = component
        sbom_dict["source"] = "api"
        sbom_dict["sha256_hash"] = sha256_hash
        sbom_dict["qualifiers"] = sbom_qualifiers
        sbom_dict["bom_type"] = bom_type

        try:
            with transaction.atomic():
                sbom = SBOM(**sbom_dict)
                sbom.save()
        except IntegrityError as e:
            _cleanup_orphaned_s3_object(filename)
            if _is_duplicate_integrity_error(e):
                return 409, {
                    "detail": f"{bom_type.upper()} artifact with version '{sbom_version}' and format '{sbom_format}' "
                    "already exists for this component",
                    "error_code": ErrorCode.DUPLICATE_ARTIFACT,
                }
            raise

        # Broadcast to workspace for real-time UI updates (non-critical)
        try:
            _broadcast_sbom_uploaded(component, sbom)
        except Exception:
            log.warning("Failed to broadcast SBOM upload notification", exc_info=True)

        # A new VEX changes which findings are suppressed; re-apply it to the component's existing
        # security scans so the dashboard reflects it without a re-scan. Run it in the background,
        # after this upload commits, so the request stays fast (the app serves on ASGI/uvicorn,
        # where a synchronous re-apply would block a worker) and the task can see the new VEX row.
        if bom_type == SBOM.BomType.VEX.value:
            schedule_vex_reapply(component.id)

        return 201, {"id": sbom.id}

    except Exception:
        log.exception("Error processing CycloneDX BOM upload")
        return 400, {"detail": "Invalid request"}


@router.post(
    "/artifact/vex/{component_id}",
    response={201: SBOMUploadRequest, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 409: ErrorResponse},
    auth=PersonalAccessTokenAuth(),
    throttle=[AccessTokenRateThrottle(), AccessTokenHeavyRateThrottle()],
)
def vex_artifact_upload(request: HttpRequest, component_id: str) -> tuple[int, dict[str, Any]]:
    """Upload a VEX document in any supported format for a component.

    The format is detected from the content: CycloneDX *JSON* VEX is delegated to
    the CycloneDX artifact flow (schema validation included); CycloneDX XML,
    OpenVEX, and CSAF VEX are stored as received without JSON-schema validation.
    Anything else is rejected.
    """
    from sbomify.apps.vulnerability_scanning.vex_formats import (
        VEX_FORMAT_CYCLONEDX,
        detect_vex_format,
    )

    try:
        from sbomify.apps.vulnerability_scanning.vex_formats import looks_like_xml, parse_vex_bytes

        # Same ceiling as the file-upload endpoint: Content-Length fails fast
        # before the body is read, len() backstops chunked/absent headers.
        max_size_mb = SBOM_MAX_UPLOAD_SIZE // (1024 * 1024)
        declared = request.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > SBOM_MAX_UPLOAD_SIZE:
            return 400, {"detail": f"Document exceeds the {max_size_mb}MB limit"}
        if len(request.body) > SBOM_MAX_UPLOAD_SIZE:
            return 400, {"detail": f"Document exceeds the {max_size_mb}MB limit"}

        document = parse_vex_bytes(request.body)
        if document is None:
            return 400, {"detail": "Invalid VEX: not a JSON or CycloneDX XML document"}

        vex_format = detect_vex_format(document)
        # The session upload flow treats any document with specVersion as
        # CycloneDX even without the bomFormat marker; stay equally lenient
        # here and let the CycloneDX schema validation give the real verdict.
        if vex_format is None and isinstance(document, dict) and "specVersion" in document:
            vex_format = VEX_FORMAT_CYCLONEDX
        if vex_format is None:
            return 400, {
                "detail": "Unrecognized VEX format. Must be CycloneDX, OpenVEX, or CSAF (csaf_vex).",
                "error_code": ErrorCode.VALIDATION_ERROR,
            }
        is_xml = looks_like_xml(request.body)
        if vex_format == VEX_FORMAT_CYCLONEDX and not is_xml:
            return sbom_upload_cyclonedx(request, component_id, bom_type=SBOM.BomType.VEX.value)

        component = Component.objects.filter(id=component_id).first()
        if component is None:
            return 404, {"detail": "Component not found"}
        if not can(request, "artifact:publish", component):
            return 403, {"detail": "Forbidden"}
        # A VEX rewrites the workspace's stored vulnerability posture, so it takes
        # the stricter publish tier (guests are excluded).
        if not can(request, "artifact:publish_vex", component):
            return 403, {"detail": "Forbidden"}
        if not is_authorised_for_component(request, component):
            return 403, {"detail": "Forbidden"}

        sha256_hash = hashlib.sha256(request.body).hexdigest()
        return _store_external_vex(component, document, request.body, sha256_hash, vex_format, source="api")

    except Exception:
        log.exception("Error processing VEX upload")
        return 400, {"detail": "Invalid request"}


@router.post(
    "/artifact/spdx/{component_id}",
    response={201: SBOMUploadRequest, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 409: ErrorResponse},
    auth=PersonalAccessTokenAuth(),
    # Per-op throttle REPLACES the global, so pass both: keep the global per-token
    # limit AND the stricter heavy-upload limit (#1070).
    throttle=[AccessTokenRateThrottle(), AccessTokenHeavyRateThrottle()],
)
def sbom_upload_spdx(request: HttpRequest, component_id: str, bom_type: str = "sbom") -> tuple[int, dict[str, Any]]:
    """
    Upload SPDX format SBOM for a component.

    Supports multiple SPDX versions. The version is detected from the spdxVersion
    field in the SBOM data, and validated accordingly.

    Args:
        component_id: The component to attach the SBOM to.
        bom_type: BOM type classification (default: "sbom"). Only "sbom" is accepted
            for SPDX uploads; other values are rejected with a 400 error.

    To add support for a new SPDX version:
    1. Add the version to SPDXSupportedVersion enum in schemas.py
    2. If needed, add version-specific schema handling in validate_spdx_sbom()
    3. That's it! The API will automatically support the new version.
    """
    if bom_type_error := _validate_bom_type(bom_type):
        return bom_type_error

    try:
        if bom_type != "sbom":
            return 400, {
                "detail": f"bom_type '{bom_type}' is not supported for SPDX uploads. Only 'sbom' is supported.",
                "error_code": ErrorCode.VALIDATION_ERROR,
            }

        component = Component.objects.filter(id=component_id).first()
        if component is None:
            return 404, {"detail": "Component not found"}

        # Allow OIDC bot tokens for trusted-publishing uploads; restrict
        # them to the bound component (see CycloneDX upload above for
        # the rationale).
        if not can(request, "artifact:publish", component):
            return 403, {"detail": "Forbidden"}
        if not is_authorised_for_component(request, component):
            return 403, {"detail": "Forbidden"}

        # Parse JSON from request body
        try:
            sbom_data = json.loads(request.body)
        except json.JSONDecodeError:
            return 400, {"detail": "Invalid JSON"}

        # Validate and get the appropriate SPDX version
        try:
            payload, spdx_version = validate_spdx_sbom(sbom_data)
        except ValueError as e:
            # Unsupported version or invalid format
            return 400, {"detail": str(e)}
        except ValidationError as e:
            # Invalid format for the detected version
            spdx_version_str = sbom_data.get("spdxVersion", "unknown")
            return 400, {"detail": f"Invalid SPDX format for {spdx_version_str}: {str(e)}"}

        # Compute SHA256 hash of the SBOM content
        sha256_hash = hashlib.sha256(request.body).hexdigest()

        # SpdxDocument.name is required in SPDX 2.x (enforced by the version-
        # specific Pydantic model above) but OPTIONAL in SPDX 3.0.1 per the
        # Core.SpdxDocument model — `name` has min-cardinality 0. Extract
        # with required=False so SPDX 3 documents without a SpdxDocument.name
        # are accepted, and fall back to the sbomify Component name to keep
        # the stored SBOM identifier non-empty. SPDX 2.x already failed
        # earlier if name was missing, so this fallback only fires for 3.x.
        sbom_dict = obj_extract(
            obj_in=payload,
            fields=[
                ExtractSpec("name", required=False, default=""),
            ],
        )
        # Treat non-string and whitespace-only names as missing so the
        # stored SBOM identifier cannot be persisted as an effectively
        # empty string. Whitespace-only passes the plain `not ...` check.
        sbom_name = sbom_dict.get("name")
        if not isinstance(sbom_name, str) or not sbom_name.strip():
            sbom_dict["name"] = component.name

        sbom_format = "spdx"
        sbom_dict["format"] = sbom_format
        sbom_dict["component"] = component
        sbom_dict["source"] = "api"
        # SPDX has no CycloneDX crypto-asset lineage; stamp crypto-free so the
        # crypto-gated plugins skip these artifacts instead of treating the
        # unstamped NULL as "maybe crypto".
        sbom_dict["has_crypto_assets"] = False
        sbom_dict["format_version"] = spdx_version  # Already extracted from validation
        sbom_dict["sha256_hash"] = sha256_hash

        # Extract primary package using format-aware helper
        primary_package, error = _extract_spdx_primary_package(payload)
        if primary_package is None:
            return 400, {"detail": error}
        sbom_version = primary_package.version

        # Extract PURL qualifiers from primary package
        sbom_qualifiers = extract_purl_qualifiers(primary_package.purl)

        # Check for duplicate (same component + version + format + qualifiers + bom_type)
        if SBOM.objects.filter(
            component=component, version=sbom_version, format=sbom_format, qualifiers=sbom_qualifiers, bom_type=bom_type
        ).exists():
            return 409, {
                "detail": f"{bom_type.upper()} artifact with version '{sbom_version}' and format '{sbom_format}' "
                "already exists for this component",
                "error_code": ErrorCode.DUPLICATE_ARTIFACT,
            }

        s3 = S3Client("SBOMS")
        filename = s3.upload_sbom(request.body)

        sbom_dict["version"] = sbom_version
        sbom_dict["sbom_filename"] = filename
        sbom_dict["qualifiers"] = sbom_qualifiers
        sbom_dict["bom_type"] = bom_type

        try:
            with transaction.atomic():
                sbom = SBOM(**sbom_dict)
                sbom.save()
        except IntegrityError as e:
            _cleanup_orphaned_s3_object(filename)
            if _is_duplicate_integrity_error(e):
                return 409, {
                    "detail": f"{bom_type.upper()} artifact with version '{sbom_version}' and format '{sbom_format}' "
                    "already exists for this component",
                    "error_code": ErrorCode.DUPLICATE_ARTIFACT,
                }
            raise

        # Broadcast to workspace for real-time UI updates (non-critical)
        try:
            _broadcast_sbom_uploaded(component, sbom)
        except Exception:
            log.warning("Failed to broadcast SBOM upload notification", exc_info=True)

        return 201, {"id": sbom.id}

    except Exception:
        return 400, {"detail": "Invalid request"}


# Moved component metadata endpoints to core API at /api/v1/components/{id}/metadata


# Removed redundant copy-meta endpoint - use GET source metadata + PATCH target instead


@router.post(
    "/artifact/cyclonedx/{spec_version}/{component_id}/metadata",
    response={
        200: cdx13.Metadata | cdx14.Metadata | cdx15.Metadata | cdx16.Metadata | cdx17.Metadata,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
    exclude_none=True,
    exclude_unset=True,
    by_alias=True,
    auth=PersonalAccessTokenAuth(),
)
def get_cyclonedx_component_metadata(
    request: HttpRequest,
    spec_version: CycloneDXSupportedVersion,
    component_id: str,
    metadata: cdx13.Metadata | cdx14.Metadata | cdx15.Metadata | cdx16.Metadata | cdx17.Metadata,
    sbom_version: str = Query(  # type: ignore[type-arg]
        None,
        description="If provided, overwrites the version present in SBOM's metadata",
    ),
    override_name: bool = Query(False, description="Override sbom name in SBOM's metadata with component name"),  # type: ignore[type-arg]
    override_metadata: bool = Query(  # type: ignore[type-arg]
        False,
        description="Override sbom metadata with component metadata. If True, if a field is "
        "present in both sbom metadata and component metadata then component metadata will be "
        "used, otherwise sbom metadata is be used",
    ),
) -> Any:
    """
    Return metadata section of cyclone-x format sbom.

    metadata provided in POST request is enriched with additional information present in the
    component and returned as response.
    """

    result = _public_api_item_access_checks(request, "component", component_id)
    if isinstance(result, tuple):
        return result

    component = result

    # Prefetch related fields for efficient metadata building
    component = (
        Component.objects.select_related("contact_profile")
        .prefetch_related("supplier_contacts", "authors", "licenses", "contact_profile__entities__contacts")
        .get(pk=component.id)
    )

    # Build ComponentMetaData from native fields and contact profile
    component_metadata = _build_component_metadata_from_native_fields(component)

    component_cdx_metadata: cdx13.Metadata | cdx14.Metadata | cdx15.Metadata | cdx16.Metadata | cdx17.Metadata = (
        component_metadata.to_cyclonedx(spec_version)
    )
    sbom_metadata_dict = metadata.model_dump(mode="json", exclude_none=True, exclude_unset=True, by_alias=True)
    component_metadata_dict = component_cdx_metadata.model_dump(
        mode="json", exclude_none=True, exclude_unset=True, by_alias=True
    )

    ### Overrides

    ## Check if there is any issue with passed metadata
    if sbom_version or override_name:
        if "component" not in sbom_metadata_dict:
            return 400, {"detail": "Missing required 'component' field in SBOM metadata"}

    if override_metadata:
        final_dict = dict_update(sbom_metadata_dict, component_metadata_dict)

    else:
        final_dict = dict_update(component_metadata_dict, sbom_metadata_dict)

    final_metadata = component_cdx_metadata.__class__(**final_dict)

    if sbom_version and final_metadata.component is not None:
        # For CycloneDX 1.3, 1.4, 1.5, version is a string
        # For 1.6+, version is a Version object whose root value is a string
        if spec_version in [
            CycloneDXSupportedVersion.v1_3,
            CycloneDXSupportedVersion.v1_4,
            CycloneDXSupportedVersion.v1_5,
        ]:
            final_metadata.component.version = sbom_version
        else:
            # 1.6, 1.7, and future versions use Version object
            from .schemas import get_cyclonedx_module

            cdx_module = get_cyclonedx_module(spec_version)
            final_metadata.component.version = cdx_module.Version(sbom_version)

    if override_name and final_metadata.component is not None:
        final_metadata.component.name = component.name

    return 200, final_metadata


# Moved dashboard summary endpoint to core API at /api/v1/dashboard/summary


@router.get(
    "/{sbom_id}",
    response={200: SBOMResponseSchema, 403: ErrorResponse, 404: ErrorResponse},
    auth=None,  # Allow unauthenticated access for public SBOMs
)
def get_sbom(request: HttpRequest, sbom_id: str) -> tuple[int, dict[str, Any]]:
    """Get a specific SBOM by ID."""
    result = get_sbom_detail(request, sbom_id)
    if not result.ok:
        return result.status_code or 400, {"detail": result.error or "Invalid request"}

    return 200, result.value or {}


@router.get(
    "/{sbom_id}/crypto-inventory",
    response={
        200: CryptoInventorySchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        503: ErrorResponse,
    },
    auth=None,  # Allow unauthenticated access for public SBOMs
)
@decorate_view(optional_auth)
def get_sbom_crypto_inventory(request: HttpRequest, sbom_id: str) -> tuple[int, dict[str, Any]]:
    """Return the derived cryptographic-asset (CBOM) inventory for an SBOM.

    Projects the ``cryptographic-asset`` components of the stored CycloneDX
    artifact. Non-crypto SBOMs return an empty inventory rather than an error.
    """
    result = get_crypto_inventory(request, sbom_id)
    if not result.ok:
        return result.status_code or 400, {"detail": result.error or "Invalid request"}

    return 200, result.value or {}


@router.get(
    "/{sbom_id}/crypto-inventory/cipher-suites.csv",
    response={200: None, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 503: ErrorResponse},
    auth=None,  # Same gate as the JSON inventory: open for public SBOMs
)
@decorate_view(optional_auth)
def download_cipher_suite_inventory_csv(request: HttpRequest, sbom_id: str) -> Any:
    """Protocol and cipher-suite inventory as CSV.

    One row per cipher suite (plus one per deprecated protocol version) with
    weakness flags — the inventory-of-suites-and-protocols evidence PCI DSS
    4.x requirement 12.3.3 asks to keep and review.
    """
    import csv
    import io

    def csv_safe(value: str) -> str:
        # Cell values come from the uploaded document. Neutralize spreadsheet
        # formula triggers so opening the export in Excel/Sheets can never
        # execute attacker-authored formulas (CSV injection).
        return f"'{value}" if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value

    result = get_crypto_inventory(request, sbom_id)
    if not result.ok:
        return result.status_code or 400, {"detail": result.error or "Invalid request"}
    inventory = result.value or {}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["protocol", "type", "version", "cipher_suite", "identifiers", "weak", "weaknesses"])
    for asset in inventory.get("assets", []):
        view = asset.get("protocol_view")
        if not view:
            continue
        base = [
            csv_safe(asset.get("name") or ""),
            csv_safe(view.get("type") or ""),
            csv_safe(view.get("version") or ""),
        ]
        if view.get("weak_version"):
            writer.writerow(base + ["", "", "yes", view["weak_version"]])
        for suite in view.get("cipher_suites", []):
            writer.writerow(
                base
                + [
                    csv_safe(suite.get("name") or ""),
                    csv_safe(" ".join(suite.get("identifiers") or [])),
                    "yes" if suite.get("weaknesses") else "no",
                    "; ".join(suite.get("weaknesses") or []),
                ]
            )
    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="cipher-suite-inventory-{sbom_id}.csv"'
    return response


@router.get(
    "/{sbom_id}/download",
    response={200: None, 403: ErrorResponse, 404: ErrorResponse, 500: ErrorResponse},
    auth=None,  # Allow unauthenticated access for public SBOMs
)
def download_sbom(request: HttpRequest, sbom_id: str) -> tuple[int, dict[str, Any]] | HttpResponse:
    """Download an SBOM file.

    This endpoint allows direct download of SBOM files. For public SBOMs,
    no authentication is required. For private SBOMs, user authentication
    and appropriate permissions are required.

    For private SBOMs included in aggregated product SBOMs, signed URLs are used instead
    to provide secure, time-limited access without requiring authentication.
    See the `/download/signed` endpoint for signed URL downloads.
    """
    try:
        sbom: SBOM = get_by_uuid_or_pk(SBOM, sbom_id, select_related=("component", "component__team"))  # type: ignore[assignment]
    except SBOM.DoesNotExist:
        return 404, {"detail": "SBOM not found"}

    # Check access permissions using centralized access control
    # This handles public, gated (with approved guest access), and private components
    component = sbom.component
    access_result = check_component_access(request, component)

    if not access_result.has_access:
        # Provide helpful error message based on access result
        if access_result.requires_access_request:
            if not request.user.is_authenticated:
                return 403, {
                    "detail": "Access denied. Please request access to download this SBOM.",
                    "requires_access_request": True,
                }
            else:
                return 403, {
                    "detail": "Access denied. Your access request is pending approval or has been rejected.",
                    "requires_access_request": True,
                }
        return 403, {"detail": "Access denied"}

    if not sbom.sbom_filename:
        return 404, {"detail": "SBOM file not found"}

    try:
        s3 = S3Client("SBOMS")
        sbom_data = s3.get_sbom_data(sbom.sbom_filename)

        if sbom_data:
            response = HttpResponse(sbom_data, content_type="application/json")
            # Use SBOM name for filename
            filename = f"{sbom.name}.json" if sbom.name else f"sbom_{sbom.uuid}.json"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
        else:
            return 404, {"detail": "SBOM file not found"}

    except Exception as e:
        log.error(f"Error retrieving SBOM {sbom_id}: {e}")
        return 500, {"detail": "Error retrieving SBOM"}


@router.get(
    "/{sbom_id}/download/signed",
    response={200: None, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 500: ErrorResponse},
    auth=None,  # No authentication required - token provides authorization
)
def download_sbom_signed(
    request: HttpRequest,
    sbom_id: str,
    token: str = Query(...),  # type: ignore[type-arg]
) -> tuple[int, dict[str, Any]] | HttpResponse:
    """Download an SBOM file using a signed token.

    This endpoint allows secure, time-limited access to private SBOMs without
    requiring user authentication. It's primarily used when private SBOMs are
    included in aggregated product SBOMs as external references.

    **Security Features:**
    - Tokens expire after 7 days
    - Tokens are tied to specific SBOMs and users
    - Installation-specific signing prevents cross-site token reuse
    - Tamper-proof - any modification invalidates the token

    **Parameters:**
    - `sbom_id`: The ID of the SBOM to download
    - `token`: A signed token generated by the system for authorized access

    **Token Generation:**
    Tokens are automatically generated when creating aggregated product SBOMs that
    contain private SBOM components. They are embedded in the SBOM as external reference URLs.

    **Error Responses:**
    - 403: Invalid, expired, or mismatched token
    - 404: SBOM not found
    - 500: Server error retrieving SBOM
    """
    try:
        sbom = SBOM.objects.select_related("component").get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return 404, {"detail": "SBOM not found"}

    # Verify the signed token
    payload = verify_download_token(token)
    if not payload:
        return 403, {"detail": "Invalid or expired download token"}

    # Verify the token is for this specific SBOM
    if payload.get("sbom_id") != sbom_id:
        return 403, {"detail": "Token is not valid for this SBOM"}

    # Non-public components: the signed token only proves which artifact +
    # user the URL was minted for. It is NOT standalone authorization — we
    # re-check the token user's current access below (#997).
    if sbom.component.visibility != Component.Visibility.PUBLIC:
        # Verify the user from the token exists (and is live)
        user_id = payload.get("user_id")
        if not user_id:
            return 403, {"detail": "Invalid token: missing user information"}

        from django.contrib.auth import get_user_model

        # Match PAT auth liveness filtering: a soft-deleted / deactivated
        # account must not download via a signed URL during the purge grace
        # window (sbomify.apps.access_tokens.utils.get_user_and_token_record).
        User = get_user_model()
        try:
            token_user = User.objects.get(id=user_id, is_active=True, deleted_at__isnull=True)
        except User.DoesNotExist:
            return 403, {"detail": "Invalid token: user not found"}

        # The signed token only delegates a download; it is NOT standalone
        # authorization. Re-check the token user's CURRENT access against live
        # DB state (no session role-cache) so that revoking their
        # membership/NDA immediately invalidates a captured signed URL instead
        # of leaving it valid for the token TTL (#997).
        access_result = check_component_access_for_user(token_user, sbom.component)
        if not access_result.has_access:
            log.info(
                "Signed URL access denied for SBOM %s, user %s: %s",
                sbom_id,
                user_id,
                access_result.reason,
            )
            return 403, {"detail": "Access has been revoked or is no longer valid"}

        # Log the access for audit purposes
        log.info(f"Signed URL access to private SBOM {sbom_id} by user {user_id}")

    # Check if SBOM file exists
    if not sbom.sbom_filename:
        return 404, {"detail": "SBOM file not found"}

    try:
        s3 = S3Client("SBOMS")
        sbom_data = s3.get_sbom_data(sbom.sbom_filename)

        if sbom_data:
            response = HttpResponse(sbom_data, content_type="application/json")
            # Use SBOM name for filename
            filename = f"{sbom.name}.json" if sbom.name else f"sbom_{sbom.id}.json"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
        else:
            return 404, {"detail": "SBOM file not found"}

    except Exception as e:
        log.error(f"Error retrieving SBOM {sbom_id} via signed URL: {e}")
        return 500, {"detail": "Error retrieving SBOM"}


@router.post(
    "/upload-file/{component_id}",
    response={201: SBOMUploadRequest, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 409: ErrorResponse},
    auth=django_auth,
)
def sbom_upload_file(
    request: HttpRequest,
    component_id: str,
    sbom_file: UploadedFile = File(...),  # type: ignore[type-arg]
    bom_type: str = Query("sbom"),  # type: ignore[type-arg]
) -> tuple[int, dict[str, Any]]:
    """Upload BOM file (CycloneDX or SPDX format) for a component.

    Args:
        bom_type: Query parameter (default: "sbom"). Non-SBOM types (e.g., "vex", "cbom")
            are only supported for CycloneDX uploads; SPDX uploads reject non-"sbom" values.
    """
    if bom_type_error := _validate_bom_type(bom_type):
        return bom_type_error

    try:
        import json

        component = Component.objects.filter(id=component_id).first()
        if component is None:
            return 404, {"detail": "Component not found"}

        if not can(request, "component:manage", component):
            return 403, {"detail": "Forbidden"}

        # Validate file size before reading
        max_size = SBOM_MAX_UPLOAD_SIZE
        max_size_mb = max_size // (1024 * 1024)
        if sbom_file.size and sbom_file.size > max_size:
            return 400, {"detail": f"File size must be {max_size_mb}MB or smaller"}

        # Read file content and compute SHA256 hash incrementally
        sha256 = hashlib.sha256()
        buffer = bytearray()
        total_size = 0
        for chunk in sbom_file.chunks():
            total_size += len(chunk)
            if total_size > max_size:
                return 400, {"detail": f"File size must be {max_size_mb}MB or smaller"}
            sha256.update(chunk)
            buffer.extend(chunk)
        file_content = bytes(buffer)
        sha256_hash = sha256.hexdigest()

        # VEX arrives in three formats and two encodings (JSON, CycloneDX XML);
        # OpenVEX, CSAF, and XML-encoded CycloneDX are stored verbatim here,
        # while JSON CycloneDX VEX continues through the schema-validating
        # CycloneDX branch below.
        if bom_type == SBOM.BomType.VEX.value:
            from sbomify.apps.vulnerability_scanning.vex_formats import (
                VEX_FORMAT_CSAF,
                VEX_FORMAT_CYCLONEDX,
                VEX_FORMAT_OPENVEX,
                detect_vex_format,
                looks_like_xml,
                parse_vex_bytes,
            )

            document = parse_vex_bytes(file_content)
            if document is None:
                return 400, {"detail": "Invalid VEX: not a JSON or CycloneDX XML document"}
            vex_format = detect_vex_format(document)
            is_xml = looks_like_xml(file_content)
            if vex_format in (VEX_FORMAT_OPENVEX, VEX_FORMAT_CSAF) or (is_xml and vex_format == VEX_FORMAT_CYCLONEDX):
                return _store_external_vex(
                    component, document, file_content, sha256_hash, vex_format, source="manual_upload"
                )

        try:
            sbom_data = json.loads(file_content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"detail": "Invalid JSON file or encoding"}

        # Determine format and process accordingly
        from sbomify.apps.plugins.builtins._spdx3_helpers import is_spdx3

        if "spdxVersion" in sbom_data or is_spdx3(sbom_data):
            # SPDX format (2.x uses spdxVersion, 3.0 spec-compliant uses @context)
            if bom_type != "sbom":
                return 400, {
                    "detail": f"bom_type '{bom_type}' is not supported for SPDX uploads. Only 'sbom' is supported.",
                    "error_code": ErrorCode.VALIDATION_ERROR,
                }
            try:
                payload, spdx_version = validate_spdx_sbom(sbom_data)
            except ValueError as e:
                # Unsupported version
                return 400, {"detail": str(e)}
            except ValidationError as e:
                # Invalid format
                spdx_version_str = sbom_data.get("spdxVersion", "unknown")
                return 400, {"detail": f"Invalid SPDX format for {spdx_version_str}: {str(e)}"}

            # SpdxDocument.name is required in SPDX 2.x but OPTIONAL in
            # SPDX 3.0.1 per Core.SpdxDocument (min-cardinality 0). Accept
            # missing name on the SPDX 3 path and fall back to the sbomify
            # Component name so the stored SBOM identifier stays non-empty.
            # SPDX 2.x rejects missing name earlier via the Pydantic model.
            sbom_dict = obj_extract(
                obj_in=payload,
                fields=[
                    ExtractSpec("name", required=False, default=""),
                ],
            )
            # Treat non-string and whitespace-only names as missing so the
            # stored SBOM identifier cannot be persisted as an effectively
            # empty string.
            sbom_name = sbom_dict.get("name")
            if not isinstance(sbom_name, str) or not sbom_name.strip():
                sbom_dict["name"] = component.name

            sbom_format = "spdx"
            sbom_dict["format"] = sbom_format
            sbom_dict["component"] = component
            sbom_dict["source"] = "manual_upload"
            # SPDX has no CycloneDX crypto-asset lineage; stamp crypto-free so
            # the crypto-gated plugins skip instead of treating NULL as
            # "maybe crypto".
            sbom_dict["has_crypto_assets"] = False
            sbom_dict["format_version"] = spdx_version  # Already extracted from validation
            sbom_dict["sha256_hash"] = sha256_hash

            # Extract primary package using format-aware helper
            primary_package, error = _extract_spdx_primary_package(payload)
            if primary_package is None:
                return 400, {"detail": error}
            sbom_version = primary_package.version

            # Extract PURL qualifiers from primary package
            sbom_qualifiers = extract_purl_qualifiers(primary_package.purl)

            # Check for duplicate (same component + version + format + qualifiers + bom_type)
            if SBOM.objects.filter(
                component=component,
                version=sbom_version,
                format=sbom_format,
                qualifiers=sbom_qualifiers,
                bom_type=bom_type,
            ).exists():
                return 409, {
                    "detail": f"{bom_type.upper()} artifact with version '{sbom_version}' and format '{sbom_format}' "
                    "already exists for this component",
                    "error_code": ErrorCode.DUPLICATE_ARTIFACT,
                }

            s3 = S3Client("SBOMS")
            filename = s3.upload_sbom(file_content)

            sbom_dict["version"] = sbom_version
            sbom_dict["sbom_filename"] = filename
            sbom_dict["qualifiers"] = sbom_qualifiers
            sbom_dict["bom_type"] = bom_type

            try:
                with transaction.atomic():
                    sbom = SBOM(**sbom_dict)
                    sbom.save()
            except IntegrityError as e:
                _cleanup_orphaned_s3_object(filename)
                if _is_duplicate_integrity_error(e):
                    return 409, {
                        "detail": (
                            f"{bom_type.upper()} artifact with version '{sbom_version}'"
                            f" and format '{sbom_format}' already exists for this component"
                        ),
                        "error_code": ErrorCode.DUPLICATE_ARTIFACT,
                    }
                raise

            # Broadcast to workspace for real-time UI updates
            _broadcast_sbom_uploaded(component, sbom)

            return 201, {"id": sbom.id}

        elif "specVersion" in sbom_data:
            # CycloneDX format
            try:
                cdx_payload, spec_version = validate_cyclonedx_sbom(sbom_data)
            except ValueError as e:
                # Unsupported version
                return 400, {"detail": str(e)}
            except ValidationError as e:
                # Invalid format
                spec_version = sbom_data.get("specVersion", "unknown")
                return 400, {"detail": f"Invalid CycloneDX {spec_version} format: {str(e)}"}

            sbom_dict = obj_extract(
                obj_in=cdx_payload,
                fields=[
                    ExtractSpec("metadata.component.name", required=False, default="", rename_to="name"),
                    ExtractSpec("metadata.component.version", required=False, rename_to="version"),
                    ExtractSpec("specVersion", required=True, rename_to="format_version"),
                ],
            )

            # metadata.component is optional in CycloneDX; fall back to the sbomify Component name
            if not sbom_dict.get("name"):
                sbom_dict["name"] = component.name

            # Version if present is a Version class and needs to be converted to string.
            if "version" in sbom_dict and not isinstance(sbom_dict["version"], str):
                sbom_dict["version"] = sbom_dict["version"].model_dump(exclude_none=True)

            sbom_version = sbom_dict.get("version", "")
            sbom_format = "cyclonedx"

            # Auto-detect CBOM content: tag a crypto BOM uploaded with the
            # default bom_type as cbom so the cbom-gated PQC plugin runs. Only when
            # the caller omitted bom_type — an explicit ?bom_type=sbom is honored.
            if "bom_type" not in request.GET and _is_cbom(sbom_data):
                bom_type = "cbom"
            sbom_dict["has_crypto_assets"] = _contains_crypto_assets(sbom_data)

            # Extract PURL qualifiers from metadata.component.purl
            cdx_purl = _extract_cdx_purl(cdx_payload)
            sbom_qualifiers = extract_purl_qualifiers(cdx_purl) if cdx_purl else {}

            # Check for duplicate (same component + version + format + qualifiers + bom_type).
            # VEX is exempt (re-issued continuously with no meaningful version; rows coexist
            # and the latest wins by created_at), mirroring the API endpoint.
            if (
                bom_type != SBOM.BomType.VEX
                and SBOM.objects.filter(
                    component=component,
                    version=sbom_version,
                    format=sbom_format,
                    qualifiers=sbom_qualifiers,
                    bom_type=bom_type,
                ).exists()
            ):
                return 409, {
                    "detail": f"{bom_type.upper()} artifact with version '{sbom_version}' and format '{sbom_format}' "
                    "already exists for this component",
                    "error_code": ErrorCode.DUPLICATE_ARTIFACT,
                }

            s3 = S3Client("SBOMS")
            filename = s3.upload_sbom(file_content)

            sbom_dict["format"] = sbom_format
            sbom_dict["sbom_filename"] = filename
            sbom_dict["component"] = component
            sbom_dict["source"] = "manual_upload"
            sbom_dict["sha256_hash"] = sha256_hash
            sbom_dict["qualifiers"] = sbom_qualifiers
            sbom_dict["bom_type"] = bom_type

            try:
                with transaction.atomic():
                    sbom = SBOM(**sbom_dict)
                    sbom.save()
            except IntegrityError as e:
                _cleanup_orphaned_s3_object(filename)
                if _is_duplicate_integrity_error(e):
                    return 409, {
                        "detail": (
                            f"{bom_type.upper()} artifact with version '{sbom_version}'"
                            f" and format '{sbom_format}' already exists for this component"
                        ),
                        "error_code": ErrorCode.DUPLICATE_ARTIFACT,
                    }
                raise

            # Broadcast to workspace for real-time UI updates
            _broadcast_sbom_uploaded(component, sbom)

            # A new VEX changes which findings are suppressed; re-apply it to the
            # component's stored scans, mirroring the API artifact endpoint.
            if bom_type == SBOM.BomType.VEX.value:
                schedule_vex_reapply(component.id)

            return 201, {"id": sbom.id}

        else:
            return 400, {"detail": "Unrecognized SBOM format. Must be SPDX or CycloneDX."}

    except Exception as e:
        log.error(f"Error processing file upload: {str(e)}")
        return 400, {"detail": "Invalid request"}


# =============================================================================
# BACKWARD COMPATIBILITY ALIASES
# =============================================================================

# Register the same functions under the old routes for backward compatibility
router.get(
    "/component/{component_id}/meta",
    response={
        200: ComponentMetaData,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
    exclude_none=True,
    auth=None,
    operation_id="sboms_get_component_metadata",
)(decorate_view(optional_auth)(get_component_metadata))

router.patch(
    "/component/{component_id}/meta",
    response={
        204: None,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
    operation_id="sboms_patch_component_metadata",
)(patch_component_metadata)


@router.delete(
    "/sbom/{sbom_id}",
    response={204: None, 403: ErrorResponse, 404: ErrorResponse},
    auth=(PersonalAccessTokenAuth(), django_auth),
)
def delete_sbom(request: HttpRequest, sbom_id: str) -> tuple[int, dict[str, Any] | None]:
    """Delete an SBOM by ID."""
    result = delete_sbom_record(request, sbom_id)
    if not result.ok:
        return result.status_code or 400, {"detail": result.error or "Invalid request"}

    return 204, None


# ============================================================================
# Signature & Provenance endpoints
# ============================================================================

_VALID_SIGNATURE_TYPES = {"cosign-bundle", "pgp-detached", "pkcs7"}
_MAX_SIGNATURE_SIZE = 5 * 1024 * 1024  # 5 MB
_MAX_PROVENANCE_SIZE = 10 * 1024 * 1024  # 10 MB


def _get_sbom_or_error(request: HttpRequest, sbom_id: str, *, write: bool = False) -> SBOM | tuple[int, dict[str, Any]]:
    """Look up an SBOM and verify access. Returns SBOM or (status, error_dict).

    For write=True (uploads), requires owner/admin via can("sbom:manage", ...).
    For write=False (downloads), uses can("component:access", ...): the same
    visibility/NDA logic as check_component_access plus the API-token scope gate,
    so public SBOMs stay downloadable while a non-read-scoped token is denied.
    """
    sbom = SBOM.objects.select_related("component", "component__team").filter(pk=sbom_id).first()
    if sbom is None:
        return 404, {"detail": "SBOM not found", "error_code": ErrorCode.NOT_FOUND}
    if write:
        if not can(request, "sbom:manage", sbom.component):
            return 403, {"detail": "Forbidden", "error_code": ErrorCode.FORBIDDEN}
    else:
        if not can(request, "component:access", sbom.component):
            return 403, {"detail": "Forbidden", "error_code": ErrorCode.FORBIDDEN}
    return sbom


def _trigger_verification(sbom_id: str) -> None:
    """Best-effort trigger of the sbom-verification plugin."""
    try:
        from sbomify.apps.plugins.sdk import RunReason
        from sbomify.apps.plugins.tasks import enqueue_assessment

        enqueue_assessment(sbom_id=sbom_id, plugin_name="sbom-verification", run_reason=RunReason.ON_UPLOAD)
    except Exception:
        log.warning("Failed to enqueue sbom-verification for SBOM %s", sbom_id, exc_info=True)


def _download_blob(
    sbom: SBOM, blob_key: str, content_type: str, filename: str
) -> tuple[int, dict[str, Any]] | HttpResponse:
    """Download a blob from S3 and return as HttpResponse."""
    try:
        s3 = S3Client("SBOMS")
        data = s3.get_sbom_data(blob_key)
        if data is None:
            return 404, {"detail": "File not found in storage", "error_code": ErrorCode.NOT_FOUND}
        response = HttpResponse(data, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
    except Exception as e:
        log.error("Error retrieving blob %s for SBOM %s: %s", blob_key, sbom.id, e)
        return 500, {"detail": "Error retrieving file", "error_code": ErrorCode.INTERNAL_ERROR}


@router.post(
    "/sbom/{sbom_id}/signature",
    response={
        201: dict,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
        500: ErrorResponse,
    },
    auth=(PersonalAccessTokenAuth(), django_auth),
)
def upload_signature(request: HttpRequest, sbom_id: str) -> tuple[int, dict[str, Any]] | HttpResponse:
    """Upload a detached cryptographic signature for an SBOM.

    The signature bytes are sent as the raw request body.
    A required ``X-Signature-Type`` header indicates the format
    (``cosign-bundle``, ``pgp-detached``, or ``pkcs7``).
    """
    result = _get_sbom_or_error(request, sbom_id, write=True)
    if not isinstance(result, SBOM):
        return result
    sbom = result

    sig_type = request.headers.get("X-Signature-Type", "").strip()
    if not sig_type:
        return 400, {"detail": "Missing X-Signature-Type header", "error_code": ErrorCode.BAD_REQUEST}
    if sig_type not in _VALID_SIGNATURE_TYPES:
        valid = ", ".join(sorted(_VALID_SIGNATURE_TYPES))
        return 400, {
            "detail": f"Invalid signature type '{sig_type}'. Must be one of: {valid}",
            "error_code": ErrorCode.BAD_REQUEST,
        }

    if not sbom.sha256_hash:
        return 400, {"detail": "SBOM has no sha256 hash; upload the SBOM first", "error_code": ErrorCode.BAD_REQUEST}

    data = request.body
    if not data:
        return 400, {"detail": "Empty request body", "error_code": ErrorCode.BAD_REQUEST}
    if len(data) > _MAX_SIGNATURE_SIZE:
        return 400, {
            "detail": f"Signature too large ({len(data)} bytes, max {_MAX_SIGNATURE_SIZE})",
            "error_code": ErrorCode.BAD_REQUEST,
        }

    try:
        # Upload to S3 first (outside lock to avoid holding DB lock during I/O)
        s3 = S3Client("SBOMS")
        blob_key = s3.upload_sbom_signature(str(sbom.id), sbom.sha256_hash, data)
        # Then lock row and atomically claim the slot
        with transaction.atomic():
            locked = SBOM.objects.select_for_update().get(pk=sbom.pk)
            if locked.signature_blob_key:
                return 409, {"detail": "Signature already exists for this SBOM", "error_code": ErrorCode.CONFLICT}
            locked.signature_blob_key = blob_key
            locked.signature_type = sig_type
            locked.save(update_fields=["signature_blob_key", "signature_type"])
    except Exception:
        log.exception("Failed to upload signature for SBOM %s", sbom.id)
        return 500, {"detail": "Failed to upload signature", "error_code": ErrorCode.INTERNAL_ERROR}

    _trigger_verification(str(sbom.id))
    return 201, {"detail": "Signature uploaded", "blob_key": blob_key}


@router.get(
    "/sbom/{sbom_id}/signature",
    response={200: None, 403: ErrorResponse, 404: ErrorResponse, 500: ErrorResponse},
    auth=None,
)
@decorate_view(optional_auth)
def download_signature(request: HttpRequest, sbom_id: str) -> tuple[int, dict[str, Any]] | HttpResponse:
    """Download the detached cryptographic signature for an SBOM."""
    result = _get_sbom_or_error(request, sbom_id, write=False)
    if not isinstance(result, SBOM):
        return result
    sbom = result

    if not sbom.signature_blob_key:
        return 404, {"detail": "No signature attached to this SBOM", "error_code": ErrorCode.NOT_FOUND}

    filename = f"{sbom.sha256_hash or sbom.id}.sig"
    resp = _download_blob(sbom, sbom.signature_blob_key, "application/octet-stream", filename)
    if isinstance(resp, HttpResponse) and sbom.signature_type:
        resp["X-Signature-Type"] = sbom.signature_type
    return resp


@router.post(
    "/sbom/{sbom_id}/provenance",
    response={
        201: dict,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        409: ErrorResponse,
        500: ErrorResponse,
    },
    auth=(PersonalAccessTokenAuth(), django_auth),
)
def upload_provenance(request: HttpRequest, sbom_id: str) -> tuple[int, dict[str, Any]] | HttpResponse:
    """Upload an in-toto provenance attestation (DSSE envelope or direct Statement) for an SBOM.

    The body must be valid JSON. For DSSE envelopes the base64-decoded payload
    is inspected; for direct Statements the body itself is inspected.
    In both cases, the ``subject`` array must contain a digest matching the
    SBOM's ``sha256_hash``.
    """
    result = _get_sbom_or_error(request, sbom_id, write=True)
    if not isinstance(result, SBOM):
        return result
    sbom = result

    if not sbom.sha256_hash:
        return 400, {"detail": "SBOM has no sha256 hash; upload the SBOM first", "error_code": ErrorCode.BAD_REQUEST}

    raw_body = request.body
    if len(raw_body) > _MAX_PROVENANCE_SIZE:
        return 400, {
            "detail": f"Provenance too large ({len(raw_body)} bytes, max {_MAX_PROVENANCE_SIZE})",
            "error_code": ErrorCode.BAD_REQUEST,
        }

    try:
        body = json.loads(raw_body)
    except (json.JSONDecodeError, ValueError):
        return 400, {"detail": "Invalid JSON", "error_code": ErrorCode.BAD_REQUEST}

    if not isinstance(body, dict):
        return 400, {"detail": "Provenance must be a JSON object", "error_code": ErrorCode.BAD_REQUEST}

    # Determine whether this is a DSSE envelope or a direct in-toto Statement
    statement: dict[str, Any] | None = None
    if "payloadType" in body and "payload" in body:
        try:
            payload_bytes = base64.b64decode(body["payload"], validate=True)
            statement = json.loads(payload_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
            return 400, {"detail": "Failed to decode DSSE envelope payload", "error_code": ErrorCode.BAD_REQUEST}
        if not isinstance(statement, dict):
            return 400, {"detail": "DSSE payload is not a JSON object", "error_code": ErrorCode.BAD_REQUEST}
    elif "_type" in body and "subject" in body:
        statement = body
    else:
        return 400, {
            "detail": (
                "Provenance must be a DSSE envelope (with payloadType/payload) or a direct Statement (with subject)"
            ),
            "error_code": ErrorCode.BAD_REQUEST,
        }

    # Validate subject digest matches SBOM hash
    subjects = statement.get("subject", [])
    if not isinstance(subjects, list) or not subjects:
        return 400, {"detail": "Provenance statement has no subjects", "error_code": ErrorCode.BAD_REQUEST}

    sbom_hash = sbom.sha256_hash

    def _subject_matches(subj: Any) -> bool:
        if not isinstance(subj, dict):
            return False
        digest = subj.get("digest")
        return isinstance(digest, dict) and digest.get("sha256") == sbom_hash

    if not any(_subject_matches(subj) for subj in subjects):
        return 400, {
            "detail": f"No subject sha256 digest matches the SBOM hash ({sbom_hash})",
            "error_code": ErrorCode.BAD_REQUEST,
        }

    try:
        # Upload to S3 first (outside lock to avoid holding DB lock during I/O)
        s3 = S3Client("SBOMS")
        blob_key = s3.upload_sbom_provenance(str(sbom.id), sbom.sha256_hash, raw_body)
        # Then lock row and atomically claim the slot
        with transaction.atomic():
            locked = SBOM.objects.select_for_update().get(pk=sbom.pk)
            if locked.provenance_blob_key:
                return 409, {"detail": "Provenance already exists for this SBOM", "error_code": ErrorCode.CONFLICT}
            locked.provenance_blob_key = blob_key
            locked.save(update_fields=["provenance_blob_key"])
    except Exception:
        log.exception("Failed to upload provenance for SBOM %s", sbom.id)
        return 500, {"detail": "Failed to upload provenance", "error_code": ErrorCode.INTERNAL_ERROR}

    _trigger_verification(str(sbom.id))
    return 201, {"detail": "Provenance uploaded", "blob_key": blob_key}


@router.get(
    "/sbom/{sbom_id}/provenance",
    response={200: None, 403: ErrorResponse, 404: ErrorResponse, 500: ErrorResponse},
    auth=None,
)
@decorate_view(optional_auth)
def download_provenance(request: HttpRequest, sbom_id: str) -> tuple[int, dict[str, Any]] | HttpResponse:
    """Download the in-toto provenance attestation for an SBOM."""
    result = _get_sbom_or_error(request, sbom_id, write=False)
    if not isinstance(result, SBOM):
        return result
    sbom = result

    if not sbom.provenance_blob_key:
        return 404, {"detail": "No provenance attached to this SBOM", "error_code": ErrorCode.NOT_FOUND}

    return _download_blob(
        sbom, sbom.provenance_blob_key, "application/json", f"{sbom.sha256_hash or sbom.id}.provenance.json"
    )
