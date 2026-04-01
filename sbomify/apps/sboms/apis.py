from __future__ import annotations

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
from sbomify.apps.core.apis import get_component_metadata, patch_component_metadata
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.core.purl import extract_purl_qualifiers
from sbomify.apps.core.schemas import ErrorCode, ErrorResponse
from sbomify.apps.core.services.access_control import check_component_access
from sbomify.apps.core.utils import (
    ExtractSpec,
    broadcast_to_workspace,
    build_entity_info_dict,
    dict_update,
    get_by_uuid_or_pk,
    obj_extract,
    verify_item_access,
)
from sbomify.apps.sboms.utils import verify_download_token
from sbomify.apps.teams.models import ContactProfile

from .models import SBOM, Component, Product, Project
from .schemas import (
    ComponentMetaData,
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
from .services.sboms import delete_sbom_record, get_sbom_detail

log = logging.getLogger(__name__)

# Max SBOM upload size in bytes (100MB — SPDX 3.0 SBOMs can be 50-100MB)
SBOM_MAX_UPLOAD_SIZE = 100 * 1024 * 1024


_SBOM_UNIQUE_CONSTRAINT = "sboms_sbom_unique_component_version_format_qualifiers_bom_type"
_VALID_BOM_TYPES = {choice[0] for choice in SBOM.BomType.choices}


def _validate_bom_type(bom_type: str) -> tuple[int, dict[str, Any]] | None:
    """Validate bom_type against BomType enum. Returns error response tuple or None if valid."""
    if bom_type not in _VALID_BOM_TYPES:
        return 400, {
            "detail": f"Invalid bom_type '{bom_type}'. Must be one of: {', '.join(sorted(_VALID_BOM_TYPES))}",
            "error_code": ErrorCode.VALIDATION_ERROR,
        }
    return None


def _is_duplicate_integrity_error(exc: IntegrityError) -> bool:
    """Check if an IntegrityError is for the SBOM uniqueness constraint.

    Postgres path: checks diag.constraint_name, then SQLSTATE 23505 with
    constraint name in the message.
    SQLite path: checks for "UNIQUE constraint failed" with the relevant columns.
    """
    cause = exc.__cause__
    if cause is not None:
        # Try PostgreSQL diagnostics first (most precise)
        diag = getattr(cause, "diag", None)
        if diag is not None:
            diag_constraint: str | None = getattr(diag, "constraint_name", None)
            if diag_constraint == _SBOM_UNIQUE_CONSTRAINT:
                return True

        pgcode: str | None = getattr(cause, "pgcode", None)
        if pgcode == "23505":
            return _SBOM_UNIQUE_CONSTRAINT in str(exc).lower()

    msg = str(exc).lower()

    # Postgres fallback (no __cause__ or missing diag)
    if _SBOM_UNIQUE_CONSTRAINT in msg:
        return True

    # SQLite: "UNIQUE constraint failed: sboms_sbom.component_id, ..."
    if "unique constraint failed" in msg and "sboms_sbom.component_id" in msg and "sboms_sbom.version" in msg:
        return True

    return False


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


item_type_map = {"component": Component, "project": Project, "product": Product}


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
) -> Component | Project | Product | tuple[int, dict[str, str]]:
    if item_type not in item_type_map:
        return 400, {"detail": "Invalid item type"}

    model_class = item_type_map[item_type]

    rec: Component | Project | Product = get_object_or_404(model_class, pk=item_id)  # type: ignore[assignment]

    if not verify_item_access(request, rec, ["owner", "admin"]):
        return 403, {"detail": "Forbidden"}

    return rec


@router.post(
    "/artifact/cyclonedx/{component_id}",
    response={201: SBOMUploadRequest, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 409: ErrorResponse},
    auth=PersonalAccessTokenAuth(),
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

        if not verify_item_access(request, component, ["owner", "admin"]):
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
                ExtractSpec("metadata.component.name", required=True, rename_to="name"),
                ExtractSpec("metadata.component.version", required=False, rename_to="version"),
                ExtractSpec("specVersion", required=True, rename_to="format_version"),
            ],
        )

        # Version if present is a Version class and needs to be converted to string.
        if "version" in sbom_dict and not isinstance(sbom_dict["version"], str):
            sbom_dict["version"] = sbom_dict["version"].model_dump(exclude_none=True)

        sbom_version = sbom_dict.get("version", "")
        sbom_format = "cyclonedx"

        # Extract PURL qualifiers from metadata.component.purl
        cdx_purl = _extract_cdx_purl(payload)
        sbom_qualifiers = extract_purl_qualifiers(cdx_purl) if cdx_purl else {}

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

        return 201, {"id": sbom.id}

    except Exception as e:
        log.error(f"Error processing CycloneDX BOM upload: {str(e)}")
        return 400, {"detail": "Invalid request"}


@router.post(
    "/artifact/spdx/{component_id}",
    response={201: SBOMUploadRequest, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 409: ErrorResponse},
    auth=PersonalAccessTokenAuth(),
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

        if not verify_item_access(request, component, ["owner", "admin"]):
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

        sbom_dict = obj_extract(
            obj_in=payload,
            fields=[
                ExtractSpec("name", required=True),
            ],
        )

        sbom_format = "spdx"
        sbom_dict["format"] = sbom_format
        sbom_dict["component"] = component
        sbom_dict["source"] = "api"
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
    "/{sbom_id}/download",
    response={200: None, 403: ErrorResponse, 404: ErrorResponse, 500: ErrorResponse},
    auth=None,  # Allow unauthenticated access for public SBOMs
)
def download_sbom(request: HttpRequest, sbom_id: str) -> tuple[int, dict[str, Any]] | HttpResponse:
    """Download an SBOM file.

    This endpoint allows direct download of SBOM files. For public SBOMs,
    no authentication is required. For private SBOMs, user authentication
    and appropriate permissions are required.

    For private SBOMs in product/project SBOMs, signed URLs are used instead
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
    included in product/project SBOMs as external references.

    **Security Features:**
    - Tokens expire after 7 days
    - Tokens are tied to specific SBOMs and users
    - Installation-specific signing prevents cross-site token reuse
    - Tamper-proof - any modification invalidates the token

    **Parameters:**
    - `sbom_id`: The ID of the SBOM to download
    - `token`: A signed token generated by the system for authorized access

    **Token Generation:**
    Tokens are automatically generated when creating product/project SBOMs that
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

    # For private components, we need to ensure the token is valid
    # The token itself provides the authorization
    if sbom.component.visibility != Component.Visibility.PUBLIC:
        # Additional security: verify the user from the token exists
        user_id = payload.get("user_id")
        if not user_id:
            return 403, {"detail": "Invalid token: missing user information"}

        try:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            User.objects.get(id=user_id)
        except User.DoesNotExist:
            return 403, {"detail": "Invalid token: user not found"}

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

        if not verify_item_access(request, component, ["owner", "admin"]):
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

            sbom_dict = obj_extract(
                obj_in=payload,
                fields=[
                    ExtractSpec("name", required=True),
                ],
            )

            sbom_format = "spdx"
            sbom_dict["format"] = sbom_format
            sbom_dict["component"] = component
            sbom_dict["source"] = "manual_upload"
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
                    ExtractSpec("metadata.component.name", required=True, rename_to="name"),
                    ExtractSpec("metadata.component.version", required=False, rename_to="version"),
                    ExtractSpec("specVersion", required=True, rename_to="format_version"),
                ],
            )

            # Version if present is a Version class and needs to be converted to string.
            if "version" in sbom_dict and not isinstance(sbom_dict["version"], str):
                sbom_dict["version"] = sbom_dict["version"].model_dump(exclude_none=True)

            sbom_version = sbom_dict.get("version", "")
            sbom_format = "cyclonedx"

            # Extract PURL qualifiers from metadata.component.purl
            cdx_purl = _extract_cdx_purl(cdx_payload)
            sbom_qualifiers = extract_purl_qualifiers(cdx_purl) if cdx_purl else {}

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
