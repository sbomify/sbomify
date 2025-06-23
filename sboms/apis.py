import logging

from django.db import transaction
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import File, Query, Router, UploadedFile
from ninja.decorators import decorate_view
from ninja.security import django_auth
from pydantic import ValidationError

from access_tokens.auth import PersonalAccessTokenAuth, optional_auth, optional_token_auth
from core.object_store import S3Client
from core.schemas import ErrorResponse
from core.utils import ExtractSpec, dict_update, obj_extract
from sbomify.tasks import scan_sbom_for_vulnerabilities
from teams.models import Team
from teams.utils import get_user_teams

from .models import SBOM, Component, Product, Project
from .schemas import (
    ComponentMetaData,
    ComponentMetaDataPatch,
    ComponentMetaDataUpdate,
    CopyComponentMetadataRequest,
    CycloneDXSupportedVersion,
    DashboardSBOMUploadInfo,
    DashboardStatsResponse,
    ItemTypes,
    PublicStatusSchema,
    SBOMUploadRequest,
    SPDXPackage,
    SPDXSchema,
    UserItemsResponse,
    cdx15,
    cdx16,
)
from .utils import verify_item_access

log = logging.getLogger(__name__)

router = Router(tags=["SBOMs"], auth=(PersonalAccessTokenAuth(), django_auth))

item_type_map = {"component": Component, "project": Project, "product": Product}


def _public_api_item_access_checks(request, item_type: str, item_id: str):
    if item_type not in item_type_map:
        return 400, {"detail": "Invalid item type"}

    Model = item_type_map[item_type]

    rec = get_object_or_404(Model, pk=item_id)

    if not verify_item_access(request, rec, ["owner", "admin"]):
        return 403, {"detail": "Forbidden"}

    return rec


@router.get(
    "/{item_type}/{item_id}/public_status",
    response={
        200: PublicStatusSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
)
def get_item_public_status(request, item_type: str, item_id: str):
    result = _public_api_item_access_checks(request, item_type, item_id)
    if isinstance(result, tuple):
        return result

    return {"is_public": result.is_public}


@router.patch(
    "/{item_type}/{item_id}/public_status",
    response={
        200: PublicStatusSchema,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
)
def patch_item_public_status(request, item_type: str, item_id: str, payload: PublicStatusSchema):
    result = _public_api_item_access_checks(request, item_type, item_id)
    if isinstance(result, tuple):
        return result

    result.is_public = payload.is_public
    result.save()

    return {"is_public": result.is_public}


@router.get(
    "/user-items/{item_type}",
    response={
        200: list[UserItemsResponse],
        400: ErrorResponse,
    },
)
def get_user_items(request, item_type: ItemTypes) -> list[UserItemsResponse]:
    "Get all items of a sepecifc type (across all teams) that belong to the current user."
    user_teams = get_user_teams(user=request.user, include_team_id=True)
    Model = item_type_map[item_type]

    result = []
    team_id_to_key = {v["team_id"]: k for k, v in user_teams.items() if "team_id" in v}
    item_records = Model.objects.filter(team_id__in=team_id_to_key.keys())

    for item in item_records:
        team_key = team_id_to_key[item.team_id]
        result.append(
            UserItemsResponse(
                team_key=team_key,
                team_name=user_teams[team_key]["name"],
                item_key=item.id,
                item_name=item.name,
            )
        )

    return result


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

        # Trigger vulnerability scan for the new SBOM with a 30 second delay
        scan_sbom_for_vulnerabilities.send_with_options(args=[sbom.id], delay=30000)

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

        # Trigger vulnerability scan for the new SBOM with a 30 second delay
        scan_sbom_for_vulnerabilities.send_with_options(args=[sbom.id], delay=30000)

        return 201, {"id": sbom.id}

    except Exception as e:
        return 400, {"detail": str(e)}


@router.get(
    "/component/{component_id}/meta",
    response={
        200: ComponentMetaData,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
    exclude_none=True,
    auth=None,
)
@decorate_view(optional_auth)
def get_component_metadata(request, component_id: str):
    result = _public_api_item_access_checks(request, "component", component_id)
    if isinstance(result, tuple):
        return result

    metadata = result.metadata or {}

    # Remove extra fields from contacts and authors
    def strip_extra_fields(obj_list):
        allowed = {"name", "email", "phone"}
        return [
            {k: v for k, v in obj.items() if k in allowed and v is not None}
            for obj in obj_list
            if isinstance(obj, dict)
        ]

    supplier = metadata.get("supplier", {})
    if "contacts" in supplier:
        supplier["contacts"] = strip_extra_fields(supplier["contacts"])
    metadata["supplier"] = supplier

    if "authors" in metadata:
        metadata["authors"] = strip_extra_fields(metadata["authors"])

    # Include component id and name in the response
    metadata["id"] = result.id
    metadata["name"] = result.name

    return metadata


@router.put(
    "/component/{component_id}/meta",
    response={
        204: None,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
)
def update_component_metadata(request, component_id: str, metadata: ComponentMetaDataUpdate):
    "Update metadata for a component."
    log.debug(f"Incoming metadata payload for component {component_id}: {request.body}")
    try:
        result = _public_api_item_access_checks(request, "component", component_id)
        if isinstance(result, tuple):
            return result

        # Convert to dict and validate licenses
        meta_dict = metadata.model_dump()
        licenses = meta_dict.get("licenses", [])
        if licenses is None:
            licenses = []
        meta_dict["licenses"] = licenses

        log.debug(f"Final metadata to be saved: {meta_dict}")
        result.metadata = meta_dict
        result.save()
        return 204, None
    except ValidationError as ve:
        log.error(f"Pydantic validation error for component {component_id}: {ve.errors()}")
        log.error(f"Failed validation data: {metadata.model_dump()}")
        return 422, {"detail": str(ve.errors())}
    except Exception as e:
        log.error(f"Error updating component metadata for {component_id}: {e}", exc_info=True)
        return 400, {"detail": str(e)}


@router.patch(
    "/component/{component_id}/meta",
    response={
        204: None,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
)
def patch_component_metadata(request, component_id: str, metadata: ComponentMetaDataPatch):
    "Partially update metadata for a component."
    log.debug(f"Incoming metadata payload for component {component_id}: {request.body}")
    try:
        result = _public_api_item_access_checks(request, "component", component_id)
        if isinstance(result, tuple):
            return result

        # Get existing metadata
        existing_metadata = result.metadata or {}

        # Convert incoming metadata to dict, excluding unset fields
        meta_dict = metadata.model_dump(exclude_unset=True)

        # Only process licenses if they were explicitly provided in the request
        if "licenses" in meta_dict:
            licenses = meta_dict.get("licenses", [])
            if licenses is None:
                licenses = []
            meta_dict["licenses"] = licenses

        # Merge with existing metadata
        updated_metadata = {**existing_metadata, **meta_dict}

        log.debug(f"Final metadata to be saved: {updated_metadata}")
        result.metadata = updated_metadata
        result.save()
        return 204, None
    except ValidationError as ve:
        log.error(f"Pydantic validation error for component {component_id}: {ve.errors()}")
        log.error(f"Failed validation data: {metadata.model_dump()}")
        return 422, {"detail": str(ve.errors())}
    except Exception as e:
        log.error(f"Error updating component metadata for {component_id}: {e}", exc_info=True)
        return 400, {"detail": str(e)}


@router.put(
    "/component/copy-meta",
    response={
        204: None,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
)
def copy_component_metadata(request, copy_request: CopyComponentMetadataRequest):
    "Copy metadata from one component to another."

    source_component = get_object_or_404(Component, pk=copy_request.source_component_id)
    target_component = get_object_or_404(Component, pk=copy_request.target_component_id)

    if not verify_item_access(request, source_component, ["guest", "owner", "admin"]):
        return 403, {"detail": "Forbidden"}

    if not verify_item_access(request, target_component, ["owner", "admin"]):
        return 403, {"detail": "Forbidden"}

    target_component.metadata = source_component.metadata
    target_component.save()

    return 204, None


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


@router.get(
    "/dashboard/summary/",
    response={200: DashboardStatsResponse, 403: ErrorResponse},
    auth=None,
)
@decorate_view(optional_token_auth)
def get_dashboard_summary(request: HttpRequest, component_id: str | None = Query(None)):
    """Retrieve a summary of SBOM statistics and latest uploads for the user's teams."""
    if not request.user or not request.user.is_authenticated:
        return 403, {"detail": "Authentication required."}

    user_teams_qs = Team.objects.filter(member__user=request.user)

    total_products = Product.objects.filter(team__in=user_teams_qs).count()
    total_projects = Project.objects.filter(team__in=user_teams_qs).count()
    total_components = Component.objects.filter(team__in=user_teams_qs).count()

    latest_sboms_qs = SBOM.objects.filter(component__team__in=user_teams_qs).select_related("component")

    if component_id:
        latest_sboms_qs = latest_sboms_qs.filter(component_id=component_id)

    latest_sboms_qs = latest_sboms_qs.order_by("-created_at")[:5]

    latest_uploads_data = [
        DashboardSBOMUploadInfo(
            component_name=sbom.component.name,
            sbom_name=sbom.name,
            sbom_version=sbom.version,
            created_at=sbom.created_at,
        )
        for sbom in latest_sboms_qs
    ]

    return 200, DashboardStatsResponse(
        total_products=total_products,
        total_projects=total_projects,
        total_components=total_components,
        latest_uploads=latest_uploads_data,
    )


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

                # Trigger vulnerability scan
                scan_sbom_for_vulnerabilities.send_with_options(args=[sbom.id], delay=30000)

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

                # Trigger vulnerability scan
                scan_sbom_for_vulnerabilities.send_with_options(args=[sbom.id], delay=30000)

                return 201, {"id": sbom.id}

            except ValidationError as e:
                return 400, {"detail": f"Invalid CycloneDX format: {str(e)}"}

        else:
            return 400, {"detail": "Unrecognized SBOM format. Must be SPDX or CycloneDX."}

    except Exception as e:
        log.error(f"Error processing file upload: {str(e)}")
        return 400, {"detail": str(e)}
