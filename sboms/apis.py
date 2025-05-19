from typing import Literal

from django.db import transaction
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Body, Query, Router
from ninja.decorators import decorate_view
from ninja.security import django_auth

from access_tokens.auth import PersonalAccessTokenAuth, optional_auth, optional_token_auth
from core.object_store import S3Client
from core.schemas import ErrorResponse
from core.utils import ExtractSpec, dict_update, obj_extract
from teams.models import Team
from teams.utils import get_user_teams

from .custom_queries import get_stats_for_team
from .license_utils import LicenseExpressionHandler
from .models import SBOM, Component, Product, Project
from .schemas import (
    ComponentMetaData,
    CopyComponentMetadataRequest,
    CycloneDXSupportedVersion,
    DBSBOMLicense,
    ItemTypes,
    PublicStatusSchema,
    SBOMUploadRequest,
    SPDXPackage,
    SPDXSchema,
    StatsResponse,
    UserItemsResponse,
    cdx15,
    cdx16,
)
from .utils import verify_item_access

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

        # License handling. If license has id, then it's SPDX license, otherwise it's a custom license.
        if payload.metadata.component.licenses:
            licenses = []

            for l_item in payload.metadata.component.licenses.model_dump(exclude_none=True):
                l_dict: dict = l_item["license"]
                licenses.append(DBSBOMLicense(**l_dict).model_dump(exclude_none=True))

            sbom_dict["licenses"] = licenses

        # Packages licenses handling
        packages_licenses: dict[str, list] = {}
        if payload.components:
            for package_component in payload.components:
                if package_component.licenses:
                    if package_component.name not in packages_licenses:
                        packages_licenses[package_component.name] = []

                    licenses_for_pkg = []

                    for l_item in package_component.licenses.model_dump(exclude_none=True):
                        if "license" not in l_item:
                            continue

                        l_dict: dict = l_item["license"]

                        # Handle invalid long license names
                        if "name" in l_dict:
                            l_dict["name"] = l_dict["name"].split("\n")[0]

                        licenses_for_pkg.append(DBSBOMLicense(**l_dict).model_dump(exclude_none=True))

                    packages_licenses[package_component.name].extend(licenses_for_pkg)

        sbom_dict["packages_licenses"] = packages_licenses

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
        sbom_dict["licenses"] = [package.license]

        with transaction.atomic():
            sbom = SBOM(**sbom_dict)
            sbom.save()

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
    auth=None,
)
@decorate_view(optional_auth)
def get_component_metadata(request, component_id: str):
    "Get metadata for a component."
    try:
        component = Component.objects.get(pk=component_id)
    except Component.DoesNotExist:
        return 404, {"detail": "Not found"}

    if not component.is_public:
        if not verify_item_access(request, component, ["guest", "owner", "admin"]):
            return 403, {"detail": "Forbidden"}

    # Create a ComponentMetaData instance with default values
    metadata = ComponentMetaData()
    # Update with any existing values from component.metadata
    metadata_dict = metadata.model_dump()
    metadata_dict.update(component.metadata)
    metadata = ComponentMetaData(**metadata_dict)

    # Backward compatibility: generate 'licenses' array from 'license_expression' if present
    if metadata.license_expression:
        handler = LicenseExpressionHandler()
        try:
            licenses = handler.parse_expression(metadata.license_expression)

            def extract_symbols(expr):
                return list(getattr(expr, "symbols", []))

            license_ids = [str(s) for s in extract_symbols(licenses)]
            metadata_dict["licenses"] = license_ids
        except Exception:
            metadata_dict["licenses"] = [metadata.license_expression]

    # Always ensure license_expression is present
    if "license_expression" not in metadata_dict:
        metadata_dict["license_expression"] = None

    # Final guarantee: always include license_expression in the response
    response = dict(metadata_dict)
    if "license_expression" not in response:
        response["license_expression"] = None
    return response


@router.put(
    "/component/{component_id}/meta",
    response={
        204: None,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
)
def update_component_metadata(request, component_id: str, metadata: ComponentMetaData):
    "Update metadata for a component."

    result = _public_api_item_access_checks(request, "component", component_id)
    if isinstance(result, tuple):
        return result

    result.metadata = metadata.model_dump(exclude_unset=True, exclude_none=True)
    result.save()

    return 204, None


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
    Return metadata section of cyclone-dx format sbom.

    metadata provided in POST request is enriched with additional information present in the
    component and returned as response.
    """

    result = _public_api_item_access_checks(request, "component", component_id)
    if isinstance(result, tuple):
        return result

    component = result
    component_metadata = ComponentMetaData(**component.metadata)

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
        if spec_version == CycloneDXSupportedVersion.v1_5:
            final_metadata.component.version = sbom_version
        elif spec_version == CycloneDXSupportedVersion.v1_6:
            final_metadata.component.version = cdx16.Version(sbom_version)
    if override_name:
        final_metadata.component.name = component.name

    # After all updates, always ensure license_expression is present
    if "license_expression" not in final_dict:
        final_dict["license_expression"] = None

    # Ensure license_expression is always present in the response
    response = dict(final_dict)
    if response.get("license_expression") is None:
        response.pop("license_expression", None)

    # Convert to dict to ensure all fields are included
    return final_metadata.model_dump(mode="json", exclude_none=True, exclude_unset=True, by_alias=True)


@router.get(
    "/stats",
    response={
        200: StatsResponse,
        400: ErrorResponse,
        403: ErrorResponse,
        404: ErrorResponse,
    },
    auth=None,
)
@decorate_view(optional_token_auth)
def get_stats(
    request,
    team_key: str | None = None,
    item_type: Literal["product", "project", "component"] | None = None,
    item_id: str | None = None,
):
    """
    Retrieve statistics for a specific team based on the provided item type.
    Args:
        team_key (str): Unique identifier key for the team or None if item_type and item_id are provided.
        item_type (Literal["ALL", "product", "project", "component"]): Type of items to get stats for
        item_id (str): Optional ID of a specific item to get stats for. This is required if item_type is not 'ALL'
    Returns:
        tuple: A tuple containing:
            - int: HTTP status code
            - dict: Response data containing the statistics or error details
    """
    if item_type is None and item_id is None:
        if not request.user.is_authenticated:
            return 403, {"detail": "Authentication required"}

    if item_type and not item_id:
        return 400, {"detail": "item_id is required when item_type is provided"}

    team = None
    if team_key:
        team = Team.objects.filter(key=team_key).first()
        if team is None:
            return 404, {"detail": "Team not found"}

    if item_type and item_id:
        team = None  # No need for team if we have item_id
        if item_type == "product":
            item = Product.objects.filter(id=item_id).first()
        elif item_type == "project":
            item = Project.objects.filter(id=item_id).first()
        elif item_type == "component":
            item = Component.objects.filter(id=item_id).first()
        else:
            return 400, {"detail": "Invalid item_type"}

        if not item:
            return 404, {"detail": f"{item_type.title()} not found"}

        if not item.is_public and not request.user.is_authenticated:
            return 403, {"detail": "Authentication required"}

    # If item is public then we won't have team_id in the url query params.
    response = get_stats_for_team(team, item_type, item_id)

    return response


@router.get("/spdx_identifiers", auth=None)
def get_spdx_identifiers(request):
    """Return all SPDX license and exception identifiers, including Commons-Clause."""
    handler = LicenseExpressionHandler()
    identifiers = set(handler.spdx_licensing.known_symbols)
    identifiers.add("Commons-Clause")
    return {"identifiers": sorted(list(identifiers))}


@router.post("/validate_license_expression", auth=None)
def validate_license_expression(request, data: dict = Body(...)):
    """Validate a license expression string. Expects: { "expression": "..." }"""
    handler = LicenseExpressionHandler()
    expr = data.get("expression", "")
    is_valid, errors = handler.validate_expression(expr)
    return {"is_valid": is_valid, "errors": errors}
