import logging

from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from ninja import File, Query, Router, UploadedFile
from ninja.decorators import decorate_view
from ninja.security import django_auth
from pydantic import ValidationError

from access_tokens.auth import PersonalAccessTokenAuth, optional_auth
from core.apis import get_component_metadata, patch_component_metadata
from core.object_store import S3Client
from core.schemas import ErrorResponse
from core.utils import ExtractSpec, dict_update, obj_extract, verify_item_access
from sboms.utils import verify_download_token

from .models import SBOM, Component, Product, Project
from .schemas import (
    ComponentMetaData,
    CycloneDXSupportedVersion,
    SBOMUploadRequest,
    SPDXPackage,
    SPDXSchema,
    cdx15,
    cdx16,
)

log = logging.getLogger(__name__)

router = Router(tags=["Artifacts"], auth=(PersonalAccessTokenAuth(), django_auth))

item_type_map = {"component": Component, "project": Project, "product": Product}


# Removed duplicate component creation endpoint - use /api/v1/components instead


# Removed duplicate public_status endpoints - use core API PATCH endpoints with is_public field instead


def _public_api_item_access_checks(request, item_type: str, item_id: str):
    if item_type not in item_type_map:
        return 400, {"detail": "Invalid item type"}

    Model = item_type_map[item_type]

    rec = get_object_or_404(Model, pk=item_id)

    if not verify_item_access(request, rec, ["owner", "admin"]):
        return 403, {"detail": "Forbidden"}

    return rec


@router.post(
    "/artifact/cyclonedx/{component_id}",
    response={201: SBOMUploadRequest, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=PersonalAccessTokenAuth(),
)
def sbom_upload_cyclonedx(
    request: HttpRequest,
    component_id: str,
    payload: cdx15.CyclonedxSoftwareBillOfMaterialsStandard | cdx16.CyclonedxSoftwareBillOfMaterialsStandard,
):
    "Upload CycloneDX format SBOM for a component."
    try:
        component = Component.objects.filter(id=component_id).first()
        if component is None:
            return 404, {"detail": "Component not found"}

        if not verify_item_access(request, component, ["owner", "admin"]):
            return 403, {"detail": "Forbidden"}

        s3 = S3Client("SBOMS")
        filename = s3.upload_sbom(request.body)

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

        sbom_dict["format"] = "cyclonedx"
        sbom_dict["sbom_filename"] = filename
        sbom_dict["component"] = component
        sbom_dict["source"] = "api"

        with transaction.atomic():
            sbom = SBOM(**sbom_dict)
            sbom.save()

        return 201, {"id": sbom.id}

    except Exception as e:
        return 400, {"detail": str(e)}


@router.post(
    "/artifact/spdx/{component_id}",
    response={201: SBOMUploadRequest, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=PersonalAccessTokenAuth(),
)
def sbom_upload_spdx(request: HttpRequest, component_id: str, payload: SPDXSchema):
    "Upload SPDX format SBOM for a component."
    try:
        component = Component.objects.filter(id=component_id).first()
        if component is None:
            return 404, {"detail": "Component not found"}

        if not verify_item_access(request, component, ["owner", "admin"]):
            return 403, {"detail": "Forbidden"}

        s3 = S3Client("SBOMS")
        filename = s3.upload_sbom(request.body)

        sbom_dict = obj_extract(
            obj_in=payload,
            fields=[
                ExtractSpec("name", required=True),
            ],
        )

        sbom_dict["format"] = "spdx"
        sbom_dict["sbom_filename"] = filename
        sbom_dict["component"] = component
        sbom_dict["source"] = "api"
        sbom_dict["format_version"] = payload.spdx_version.removeprefix("SPDX-")

        # Error message constants
        NO_PACKAGES_ERROR = "No packages found in SPDX document"
        NO_MATCHING_PACKAGE_ERROR = "No package found with name '{name}' in SPDX document"

        if not payload.packages:
            return 400, {"detail": NO_PACKAGES_ERROR}

        """
        Find the primary package in the SPDX document using the following strategy:
        1. Look for a package referenced by documentDescribes field
        2. Fall back to matching package name with document name
        """
        package: SPDXPackage | None = None

        # First check if documentDescribes is present and points to a valid package
        if hasattr(payload, "documentDescribes") and payload.documentDescribes:
            described_ref: str = payload.documentDescribes[0]  # Usually contains "SPDXRef-..." reference
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
            return 400, {"detail": NO_MATCHING_PACKAGE_ERROR.format(name=payload.name)}

        sbom_dict["version"] = package.version

        with transaction.atomic():
            sbom = SBOM(**sbom_dict)
            sbom.save()

        return 201, {"id": sbom.id}

    except Exception as e:
        return 400, {"detail": str(e)}


# Moved component metadata endpoints to core API at /api/v1/components/{id}/metadata


# Removed redundant copy-meta endpoint - use GET source metadata + PATCH target instead


@router.post(
    "/artifact/cyclonedx/{spec_version}/{component_id}/metadata",
    response={
        200: cdx15.Metadata | cdx16.Metadata,
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
    request,
    spec_version: CycloneDXSupportedVersion,
    component_id: str,
    metadata: cdx15.Metadata | cdx16.Metadata,
    sbom_version: str = Query(
        None,
        description="If provided, overwrites the version present in SBOM's metadata",
    ),
    override_name: bool = Query(False, description="Override sbom name in SBOM's metadata with component name"),
    override_metadata: bool = Query(
        False,
        description="Override sbom metadata with component metadata. If True, if a field is "
        "present in both sbom metadata and component metadata then component metadata will be "
        "used, otherwise sbom metadata is be used",
    ),
) -> cdx15.Metadata | cdx16.Metadata:
    """
    Return metadata section of cyclone-x format sbom.

    metadata provided in POST request is enriched with additional information present in the
    component and returned as response.
    """

    result = _public_api_item_access_checks(request, "component", component_id)
    if isinstance(result, tuple):
        return result

    component = result
    metadata_dict = component.metadata or {}
    metadata_dict["id"] = component.id
    metadata_dict["name"] = component.name
    component_metadata = ComponentMetaData(**metadata_dict)

    component_cdx_metadata: cdx15.Metadata | cdx16.Metadata = component_metadata.to_cyclonedx(spec_version)
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

    if sbom_version:
        # For cyclone dx 1.5, version is a string, for 1.6, version is an Version object whose root value is string.
        if spec_version == CycloneDXSupportedVersion.v1_5:
            final_metadata.component.version = sbom_version
        elif spec_version == CycloneDXSupportedVersion.v1_6:
            final_metadata.component.version = cdx16.Version(sbom_version)

    if override_name:
        final_metadata.component.name = component.name

    return 200, final_metadata


# Moved dashboard summary endpoint to core API at /api/v1/dashboard/summary


@router.get(
    "/{sbom_id}/download",
    response={200: None, 403: ErrorResponse, 404: ErrorResponse, 500: ErrorResponse},
    auth=None,  # Allow unauthenticated access for public SBOMs
)
def download_sbom(request: HttpRequest, sbom_id: str):
    """Download an SBOM file.

    This endpoint allows direct download of SBOM files. For public SBOMs,
    no authentication is required. For private SBOMs, user authentication
    and appropriate permissions are required.

    For private SBOMs in product/project SBOMs, signed URLs are used instead
    to provide secure, time-limited access without requiring authentication.
    See the `/download/signed` endpoint for signed URL downloads.
    """
    try:
        sbom = SBOM.objects.select_related("component").get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return 404, {"detail": "SBOM not found"}

    # Check access permissions
    if sbom.public_access_allowed or (
        request.user.is_authenticated and verify_item_access(request, sbom.component, ["guest", "owner", "admin"])
    ):
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
            log.error(f"Error retrieving SBOM {sbom_id}: {e}")
            return 500, {"detail": f"Error retrieving SBOM: {str(e)}"}
    else:
        return 403, {"detail": "Access denied"}


@router.get(
    "/{sbom_id}/download/signed",
    response={200: None, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 500: ErrorResponse},
    auth=None,  # No authentication required - token provides authorization
)
def download_sbom_signed(request: HttpRequest, sbom_id: str, token: str = Query(...)):
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
    if not sbom.component.is_public:
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
        return 500, {"detail": f"Error retrieving SBOM: {str(e)}"}


@router.post(
    "/upload-file/{component_id}",
    response={201: SBOMUploadRequest, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=django_auth,
)
def sbom_upload_file(
    request: HttpRequest,
    component_id: str,
    sbom_file: UploadedFile = File(...),
):
    """Upload SBOM file (CycloneDX or SPDX format) for a component."""
    try:
        import json

        component = Component.objects.filter(id=component_id).first()
        if component is None:
            return 404, {"detail": "Component not found"}

        if not verify_item_access(request, component, ["owner", "admin"]):
            return 403, {"detail": "Forbidden"}

        # Read file content
        file_content = sbom_file.read()

        # Validate file size (max 10MB)
        max_size = 10 * 1024 * 1024
        if len(file_content) > max_size:
            return 400, {"detail": "File size must be less than 10MB"}

        try:
            sbom_data = json.loads(file_content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"detail": "Invalid JSON file or encoding"}

        # Determine format and process accordingly
        if "spdxVersion" in sbom_data:
            # SPDX format
            try:
                payload = SPDXSchema(**sbom_data)

                s3 = S3Client("SBOMS")
                filename = s3.upload_sbom(file_content)

                sbom_dict = obj_extract(
                    obj_in=payload,
                    fields=[
                        ExtractSpec("name", required=True),
                    ],
                )

                sbom_dict["format"] = "spdx"
                sbom_dict["sbom_filename"] = filename
                sbom_dict["component"] = component
                sbom_dict["source"] = "manual_upload"
                sbom_dict["format_version"] = payload.spdx_version.removeprefix("SPDX-")

                # Error message constants
                NO_PACKAGES_ERROR = "No packages found in SPDX document"
                NO_MATCHING_PACKAGE_ERROR = "No package found with name '{name}' in SPDX document"

                if not payload.packages:
                    return 400, {"detail": NO_PACKAGES_ERROR}

                # Find the primary package
                package: SPDXPackage | None = None

                # First check documentDescribes
                if hasattr(payload, "documentDescribes") and payload.documentDescribes:
                    described_ref: str = payload.documentDescribes[0]
                    for pkg in payload.packages:
                        if hasattr(pkg, "SPDXID") and pkg.SPDXID == described_ref:
                            package = pkg
                            break

                # Fall back to name matching
                if not package:
                    for pkg in payload.packages:
                        if pkg.name == payload.name:
                            package = pkg
                            break

                if not package:
                    return 400, {"detail": NO_MATCHING_PACKAGE_ERROR.format(name=payload.name)}

                sbom_dict["version"] = package.version

                with transaction.atomic():
                    sbom = SBOM(**sbom_dict)
                    sbom.save()

                return 201, {"id": sbom.id}

            except ValidationError as e:
                return 400, {"detail": f"Invalid SPDX format: {str(e)}"}

        elif "specVersion" in sbom_data:
            # CycloneDX format
            try:
                spec_version = sbom_data.get("specVersion", "1.5")
                if spec_version == "1.5":
                    payload = cdx15.CyclonedxSoftwareBillOfMaterialsStandard(**sbom_data)
                elif spec_version == "1.6":
                    payload = cdx16.CyclonedxSoftwareBillOfMaterialsStandard(**sbom_data)
                else:
                    return 400, {"detail": f"Unsupported CycloneDX specVersion: {spec_version}"}

                s3 = S3Client("SBOMS")
                filename = s3.upload_sbom(file_content)

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

                sbom_dict["format"] = "cyclonedx"
                sbom_dict["sbom_filename"] = filename
                sbom_dict["component"] = component
                sbom_dict["source"] = "manual_upload"

                with transaction.atomic():
                    sbom = SBOM(**sbom_dict)
                    sbom.save()

                return 201, {"id": sbom.id}

            except ValidationError as e:
                return 400, {"detail": f"Invalid CycloneDX format: {str(e)}"}

        else:
            return 400, {"detail": "Unrecognized SBOM format. Must be SPDX or CycloneDX."}

    except Exception as e:
        log.error(f"Error processing file upload: {str(e)}")
        return 400, {"detail": str(e)}


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
def delete_sbom(request: HttpRequest, sbom_id: str):
    """Delete an SBOM by ID."""
    try:
        sbom = SBOM.objects.get(pk=sbom_id)
    except SBOM.DoesNotExist:
        return 404, {"detail": "SBOM not found"}

    # Check if user has permission to delete this SBOM (must be owner/admin of component)
    if not verify_item_access(request, sbom.component, ["owner", "admin"]):
        return 403, {"detail": "Only owners or admins of the component can delete SBOMs"}

    # Delete the SBOM file from S3 if it exists
    if sbom.sbom_filename:
        try:
            s3 = S3Client("SBOMS")
            s3.delete_object(settings.AWS_SBOMS_STORAGE_BUCKET_NAME, sbom.sbom_filename)
        except Exception as e:
            log.warning(f"Failed to delete SBOM file {sbom.sbom_filename} from S3: {str(e)}")
            # Continue with database deletion even if S3 deletion fails

    # Delete the SBOM record from database
    sbom.delete()

    return 204, None
