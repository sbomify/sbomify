"""
TEA (Transparency Exchange API) endpoints.

Based on TEA OpenAPI Spec v0.3.0-beta.2.
All endpoints are public and workspace-scoped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from ninja import Query, Router

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.sboms.utils import get_download_url_for_document
from sbomify.apps.tea.mappers import (
    TEA_API_VERSION,
    TEA_IDENTIFIER_TYPE_MAPPING,
    TEIParseError,
    build_tea_server_url,
    tea_component_identifier_mapper,
    tea_identifier_mapper,
    tea_tei_mapper,
)
from sbomify.apps.tea.schemas import (
    TEAArtifact,
    TEAArtifactFormat,
    TEAChecksum,
    TEACollection,
    TEACollectionUpdateReason,
    TEAComponent,
    TEAComponentRef,
    TEAComponentReleaseWithCollection,
    TEADiscoveryInfo,
    TEAErrorResponse,
    TEAPaginatedProductReleaseResponse,
    TEAPaginatedProductResponse,
    TEAProduct,
    TEAProductRelease,
    TEARelease,
    TEAServerInfo,
)
from sbomify.apps.tea.utils import get_artifact_mime_type, get_tea_artifact_type, get_workspace_from_request
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.sboms.models import SBOM
    from sbomify.apps.teams.models import Team

log = getLogger(__name__)

router = Router(tags=["TEA"], auth=None)


# =============================================================================
# Helper Functions
# =============================================================================


def _build_product_response(product: Product) -> TEAProduct:
    """Build TEA Product response from sbomify Product."""
    return TEAProduct(
        uuid=product.id,
        name=product.name,
        identifiers=tea_identifier_mapper(product),
    )


def _build_product_release_response(
    release: Release,
    include_components: bool = True,
) -> TEAProductRelease:
    """Build TEA Product Release response from sbomify Release."""
    components = []

    if include_components:
        # Get all components from this product's projects with prefetched artifacts
        # Use a single query to get component-artifact mappings
        release_artifacts = {
            artifact.sbom.component_id: artifact.sbom.id
            for artifact in release.artifacts.select_related("sbom__component").all()
            if artifact.sbom and artifact.sbom.component_id
        }

        product_components = Component.objects.filter(projects__products=release.product).distinct()

        for component in product_components:
            component_ref = TEAComponentRef(
                uuid=component.id,
                release=release_artifacts.get(component.id),
            )
            components.append(component_ref)

    return TEAProductRelease(
        uuid=release.id,
        product=release.product.id,
        productName=release.product.name,
        version=release.name,
        createdDate=release.created_at,
        releaseDate=release.released_at,
        preRelease=release.is_prerelease,
        identifiers=tea_identifier_mapper(release.product),
        components=components,
    )


def _build_component_response(component: Component) -> TEAComponent:
    """Build TEA Component response from sbomify Component."""
    return TEAComponent(
        uuid=component.id,
        name=component.name,
        identifiers=tea_component_identifier_mapper(component),
    )


def _build_component_release_response(sbom: "SBOM") -> TEARelease:
    """Build TEA Component Release response from sbomify SBOM."""
    return TEARelease(
        uuid=sbom.id,
        component=sbom.component.id,
        componentName=sbom.component.name,
        version=sbom.version or "unknown",
        createdDate=sbom.created_at,
        releaseDate=sbom.created_at,  # SBOMs don't have separate release dates
        preRelease=False,  # SBOMs don't track pre-release status
        identifiers=tea_component_identifier_mapper(sbom.component),
        distributions=[],
    )


def _get_sbom_download_url(sbom_id: str, team_id: int) -> str:
    """Get SBOM download URL from S3, with error handling."""
    try:
        s3_client = S3Client()
        return s3_client.get_sbom_download_url(sbom_id, team_id)
    except Exception as e:
        log.warning(f"Failed to generate download URL for SBOM {sbom_id}: {e}")
        return ""


def _build_artifact_response(artifact: ReleaseArtifact, team: "Team") -> TEAArtifact | None:
    """Build TEA Artifact response from sbomify ReleaseArtifact."""
    if artifact.sbom:
        sbom = artifact.sbom
        download_url = _get_sbom_download_url(sbom.id, team.id)

        # Build checksums list if SHA256 hash is available
        checksums = []
        if sbom.sha256_hash:
            checksums.append(TEAChecksum(algType="SHA-256", algValue=sbom.sha256_hash))

        return TEAArtifact(
            uuid=sbom.id,
            name=sbom.name,
            type="BOM",
            formats=[
                TEAArtifactFormat(
                    mimeType=get_artifact_mime_type(sbom.format),
                    description=f"{sbom.format.upper()} SBOM ({sbom.format_version})",
                    url=download_url,
                    checksums=checksums,
                )
            ],
        )
    elif artifact.document:
        doc = artifact.document
        download_url = get_download_url_for_document(doc, base_url=settings.APP_BASE_URL)

        # Build checksums list if SHA256 hash is available
        checksums = []
        if doc.sha256_hash:
            checksums.append(TEAChecksum(algType="SHA-256", algValue=doc.sha256_hash))

        return TEAArtifact(
            uuid=doc.id,
            name=doc.name,
            type=get_tea_artifact_type(doc.document_type),
            formats=[
                TEAArtifactFormat(
                    mimeType=doc.content_type or "application/octet-stream",
                    description=f"Document: {doc.document_type or 'unknown'}",
                    url=download_url,
                    checksums=checksums,
                )
            ],
        )
    return None


def _build_collection_response(
    release: Release,
    belongs_to: str,
    team: "Team",
) -> TEACollection:
    """Build TEA Collection response from sbomify Release artifacts."""
    artifacts = []
    for artifact in release.artifacts.all():
        tea_artifact = _build_artifact_response(artifact, team)
        if tea_artifact:
            artifacts.append(tea_artifact)

    return TEACollection(
        uuid=release.id,
        version=1,  # We don't track collection versions yet
        date=release.created_at,
        belongsTo=belongs_to,
        updateReason=TEACollectionUpdateReason(
            type="INITIAL_RELEASE",
            comment="Initial collection",
        ),
        artifacts=artifacts,
    )


def _build_sbom_collection_response(
    sbom: "SBOM",
    belongs_to: str,
    team: "Team",
) -> TEACollection:
    """Build TEA Collection response from a single SBOM."""
    download_url = _get_sbom_download_url(sbom.id, team.id)

    # Build checksums list if SHA256 hash is available
    checksums = []
    if sbom.sha256_hash:
        checksums.append(TEAChecksum(algType="SHA-256", algValue=sbom.sha256_hash))

    artifact = TEAArtifact(
        uuid=sbom.id,
        name=sbom.name,
        type="BOM",
        formats=[
            TEAArtifactFormat(
                mimeType=get_artifact_mime_type(sbom.format),
                description=f"{sbom.format.upper()} SBOM ({sbom.format_version})",
                url=download_url,
                checksums=checksums,
            )
        ],
    )

    return TEACollection(
        uuid=sbom.id,
        version=1,
        date=sbom.created_at,
        belongsTo=belongs_to,
        updateReason=TEACollectionUpdateReason(
            type="INITIAL_RELEASE",
            comment="Initial collection",
        ),
        artifacts=[artifact],
    )


# =============================================================================
# Discovery Endpoints
# =============================================================================


@router.get(
    "/discovery",
    response={200: list[TEADiscoveryInfo], 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Discover TEA resources by TEI",
    description="Discovery endpoint which resolves TEI into product release UUIDs.",
)
def discovery(
    request: HttpRequest,
    tei: str = Query(..., description="Transparency Exchange Identifier (TEI) - URL-encoded string"),
    workspace_key: str | None = Query(None, description="Workspace key (for non-custom-domain access)"),
):
    """Resolve TEI to product releases."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    try:
        releases = tea_tei_mapper(team, tei)
    except TEIParseError as e:
        return 400, TEAErrorResponse(error=str(e))

    if not releases:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    # Build discovery response for each release
    results = []
    server_url = build_tea_server_url(team, workspace_key)

    for release in releases:
        results.append(
            TEADiscoveryInfo(
                productReleaseUuid=release.id,
                servers=[
                    TEAServerInfo(
                        rootUrl=server_url,
                        versions=[TEA_API_VERSION],
                        priority=1.0,
                    )
                ],
            )
        )

    return 200, results


# =============================================================================
# Product Endpoints
# =============================================================================


@router.get(
    "/products",
    response={200: TEAPaginatedProductResponse, 400: TEAErrorResponse},
    summary="List products",
    description="Returns a list of TEA products. Can be filtered by identifier.",
)
def list_products(
    request: HttpRequest,
    workspace_key: str | None = Query(None, description="Workspace key"),
    idType: str | None = Query(None, description="Type of identifier to filter by"),
    idValue: str | None = Query(None, description="Identifier value to filter by"),
    pageOffset: int = Query(0, ge=0, description="Pagination offset"),
    pageSize: int = Query(100, ge=1, le=1000, description="Page size"),
):
    """List all products in a workspace."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    # Base queryset - only public products, prefetch identifiers for efficiency
    products = Product.objects.filter(team=team, is_public=True).prefetch_related("identifiers")

    # Filter by identifier if provided
    if idType and idValue:
        sbomify_types = TEA_IDENTIFIER_TYPE_MAPPING.get(idType.upper(), [])
        if sbomify_types:
            products = products.filter(
                identifiers__identifier_type__in=sbomify_types,
                identifiers__value__icontains=idValue,
            ).distinct()

    # Get total count
    total = products.count()

    # Apply pagination
    products = products[pageOffset : pageOffset + pageSize]

    # Build response
    results = [_build_product_response(p) for p in products]

    return 200, TEAPaginatedProductResponse(
        timestamp=timezone.now(),
        pageStartIndex=pageOffset,
        pageSize=pageSize,
        totalResults=total,
        results=results,
    )


@router.get(
    "/product/{uuid}",
    response={200: TEAProduct, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get product by UUID",
    description="Get a TEA Product by UUID.",
)
def get_product(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, description="Workspace key"),
):
    """Get a single product by UUID."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    try:
        product = Product.objects.get(id=uuid, team=team, is_public=True)
    except Product.DoesNotExist:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    return 200, _build_product_response(product)


@router.get(
    "/product/{uuid}/releases",
    response={200: TEAPaginatedProductReleaseResponse, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get product releases",
    description="Get releases of the product.",
)
def get_product_releases(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, description="Workspace key"),
    pageOffset: int = Query(0, ge=0, description="Pagination offset"),
    pageSize: int = Query(100, ge=1, le=1000, description="Page size"),
):
    """Get releases for a product."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    try:
        product = Product.objects.get(id=uuid, team=team, is_public=True)
    except Product.DoesNotExist:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    releases = product.releases.all()
    total = releases.count()

    # Apply pagination
    releases = releases[pageOffset : pageOffset + pageSize]

    results = [_build_product_release_response(r) for r in releases]

    return 200, TEAPaginatedProductReleaseResponse(
        timestamp=timezone.now(),
        pageStartIndex=pageOffset,
        pageSize=pageSize,
        totalResults=total,
        results=results,
    )


# =============================================================================
# Product Release Endpoints
# =============================================================================


@router.get(
    "/productReleases",
    response={200: TEAPaginatedProductReleaseResponse, 400: TEAErrorResponse},
    summary="Query product releases",
    description="Returns a list of TEA product releases. Can be filtered by identifier.",
)
def query_product_releases(
    request: HttpRequest,
    workspace_key: str | None = Query(None, description="Workspace key"),
    idType: str | None = Query(None, description="Type of identifier to filter by"),
    idValue: str | None = Query(None, description="Identifier value to filter by"),
    pageOffset: int = Query(0, ge=0, description="Pagination offset"),
    pageSize: int = Query(100, ge=1, le=1000, description="Page size"),
):
    """Query product releases."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    # Base queryset - only releases from public products, with prefetch for efficiency
    releases = (
        Release.objects.filter(product__team=team, product__is_public=True)
        .select_related("product")
        .prefetch_related("product__identifiers")
    )

    # Filter by identifier if provided
    if idType and idValue:
        sbomify_types = TEA_IDENTIFIER_TYPE_MAPPING.get(idType.upper(), [])
        if sbomify_types:
            releases = releases.filter(
                product__identifiers__identifier_type__in=sbomify_types,
                product__identifiers__value__icontains=idValue,
            ).distinct()

    total = releases.count()
    releases = releases[pageOffset : pageOffset + pageSize]

    results = [_build_product_release_response(r) for r in releases]

    return 200, TEAPaginatedProductReleaseResponse(
        timestamp=timezone.now(),
        pageStartIndex=pageOffset,
        pageSize=pageSize,
        totalResults=total,
        results=results,
    )


@router.get(
    "/productRelease/{uuid}",
    response={200: TEAProductRelease, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get product release by UUID",
    description="Get a TEA Product Release.",
)
def get_product_release(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, description="Workspace key"),
):
    """Get a single product release by UUID."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    try:
        release = Release.objects.get(id=uuid, product__team=team, product__is_public=True)
    except Release.DoesNotExist:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    return 200, _build_product_release_response(release)


@router.get(
    "/productRelease/{uuid}/collection/latest",
    response={200: TEACollection, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get latest collection for product release",
    description="Get the latest TEA Collection belonging to the TEA Product Release.",
)
def get_product_release_latest_collection(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, description="Workspace key"),
):
    """Get the latest collection for a product release."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    try:
        release = Release.objects.get(id=uuid, product__team=team, product__is_public=True)
    except Release.DoesNotExist:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    return 200, _build_collection_response(release, "PRODUCT_RELEASE", team)


@router.get(
    "/productRelease/{uuid}/collections",
    response={200: list[TEACollection], 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get all collections for product release",
    description="Get the TEA Collections belonging to the TEA Product Release.",
)
def get_product_release_collections(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, description="Workspace key"),
):
    """Get all collections for a product release."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    try:
        release = Release.objects.get(id=uuid, product__team=team, product__is_public=True)
    except Release.DoesNotExist:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    # We only have one collection version per release currently
    collection = _build_collection_response(release, "PRODUCT_RELEASE", team)
    return 200, [collection]


@router.get(
    "/productRelease/{uuid}/collection/{version}",
    response={200: TEACollection, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get specific collection version for product release",
    description="Get a specific Collection (by version) for a TEA Product Release.",
)
def get_product_release_collection_version(
    request: HttpRequest,
    uuid: str,
    version: int,
    workspace_key: str | None = Query(None, description="Workspace key"),
):
    """Get a specific collection version for a product release."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    try:
        release = Release.objects.get(id=uuid, product__team=team, product__is_public=True)
    except Release.DoesNotExist:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    # We only have version 1 currently
    if version != 1:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    return 200, _build_collection_response(release, "PRODUCT_RELEASE", team)


# =============================================================================
# Component Endpoints
# =============================================================================


@router.get(
    "/component/{uuid}",
    response={200: TEAComponent, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get component by UUID",
    description="Get a TEA Component.",
)
def get_component(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, description="Workspace key"),
):
    """Get a single component by UUID."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    try:
        component = Component.objects.get(id=uuid, team=team, visibility=Component.Visibility.PUBLIC)
    except Component.DoesNotExist:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    return 200, _build_component_response(component)


@router.get(
    "/component/{uuid}/releases",
    response={200: list[TEARelease], 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get component releases",
    description="Get releases of the component.",
)
def get_component_releases(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, description="Workspace key"),
):
    """Get releases (SBOMs) for a component."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    try:
        component = Component.objects.get(id=uuid, team=team, visibility=Component.Visibility.PUBLIC)
    except Component.DoesNotExist:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    # Get all SBOMs for this component - they represent "releases" in TEA terms
    sboms = component.sbom_set.all()
    results = [_build_component_release_response(sbom) for sbom in sboms]

    return 200, results


# =============================================================================
# Component Release Endpoints
# =============================================================================


@router.get(
    "/componentRelease/{uuid}",
    response={200: TEAComponentReleaseWithCollection, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get component release with collection",
    description="Get the TEA Component Release with its latest collection.",
)
def get_component_release(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, description="Workspace key"),
):
    """Get a component release (SBOM) with its collection."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    from sbomify.apps.sboms.models import SBOM

    try:
        sbom = SBOM.objects.select_related("component").get(
            id=uuid,
            component__team=team,
            component__visibility=Component.Visibility.PUBLIC,
        )
    except SBOM.DoesNotExist:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    release = _build_component_release_response(sbom)
    collection = _build_sbom_collection_response(sbom, "COMPONENT_RELEASE", team)

    return 200, TEAComponentReleaseWithCollection(
        release=release,
        latestCollection=collection,
    )


@router.get(
    "/componentRelease/{uuid}/collection/latest",
    response={200: TEACollection, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get latest collection for component release",
    description="Get the latest TEA Collection belonging to the TEA Component Release.",
)
def get_component_release_latest_collection(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, description="Workspace key"),
):
    """Get the latest collection for a component release (SBOM)."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    from sbomify.apps.sboms.models import SBOM

    try:
        sbom = SBOM.objects.select_related("component").get(
            id=uuid,
            component__team=team,
            component__visibility=Component.Visibility.PUBLIC,
        )
    except SBOM.DoesNotExist:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    return 200, _build_sbom_collection_response(sbom, "COMPONENT_RELEASE", team)


@router.get(
    "/componentRelease/{uuid}/collections",
    response={200: list[TEACollection], 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get all collections for component release",
    description="Get the TEA Collections belonging to the TEA Component Release.",
)
def get_component_release_collections(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, description="Workspace key"),
):
    """Get all collections for a component release (SBOM)."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    from sbomify.apps.sboms.models import SBOM

    try:
        sbom = SBOM.objects.select_related("component").get(
            id=uuid,
            component__team=team,
            component__visibility=Component.Visibility.PUBLIC,
        )
    except SBOM.DoesNotExist:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    # We only have one collection version per SBOM currently
    collection = _build_sbom_collection_response(sbom, "COMPONENT_RELEASE", team)
    return 200, [collection]


@router.get(
    "/componentRelease/{uuid}/collection/{version}",
    response={200: TEACollection, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get specific collection version for component release",
    description="Get a specific Collection (by version) for a TEA Component Release.",
)
def get_component_release_collection_version(
    request: HttpRequest,
    uuid: str,
    version: int,
    workspace_key: str | None = Query(None, description="Workspace key"),
):
    """Get a specific collection version for a component release (SBOM)."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    from sbomify.apps.sboms.models import SBOM

    try:
        sbom = SBOM.objects.select_related("component").get(
            id=uuid,
            component__team=team,
            component__visibility=Component.Visibility.PUBLIC,
        )
    except SBOM.DoesNotExist:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    # We only have version 1 currently
    if version != 1:
        return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")

    return 200, _build_sbom_collection_response(sbom, "COMPONENT_RELEASE", team)


# =============================================================================
# Artifact Endpoints
# =============================================================================


@router.get(
    "/artifact/{uuid}",
    response={200: TEAArtifact, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get artifact by UUID",
    description="Get metadata for specific TEA Artifact.",
)
def get_artifact(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, description="Workspace key"),
):
    """Get artifact metadata by UUID."""
    team = get_workspace_from_request(request, workspace_key)
    if not team:
        return 400, TEAErrorResponse(error="Workspace not found or not accessible")

    # Try to find as SBOM first
    from sbomify.apps.sboms.models import SBOM

    try:
        sbom = SBOM.objects.select_related("component").get(
            id=uuid,
            component__team=team,
            component__visibility=Component.Visibility.PUBLIC,
        )

        download_url = _get_sbom_download_url(sbom.id, team.id)

        # Build checksums list if SHA256 hash is available
        checksums = []
        if sbom.sha256_hash:
            checksums.append(TEAChecksum(algType="SHA-256", algValue=sbom.sha256_hash))

        return 200, TEAArtifact(
            uuid=sbom.id,
            name=sbom.name,
            type="BOM",
            formats=[
                TEAArtifactFormat(
                    mimeType=get_artifact_mime_type(sbom.format),
                    description=f"{sbom.format.upper()} SBOM ({sbom.format_version})",
                    url=download_url,
                    checksums=checksums,
                )
            ],
        )
    except SBOM.DoesNotExist:
        pass

    # Try to find as Document
    from sbomify.apps.documents.models import Document

    try:
        document = Document.objects.select_related("component").get(
            id=uuid,
            component__team=team,
            component__visibility=Component.Visibility.PUBLIC,
        )

        download_url = get_download_url_for_document(document, base_url=settings.APP_BASE_URL)

        # Build checksums list if SHA256 hash is available
        checksums = []
        if document.sha256_hash:
            checksums.append(TEAChecksum(algType="SHA-256", algValue=document.sha256_hash))

        return 200, TEAArtifact(
            uuid=document.id,
            name=document.name,
            type=get_tea_artifact_type(document.document_type),
            formats=[
                TEAArtifactFormat(
                    mimeType=document.content_type or "application/octet-stream",
                    description=f"Document: {document.document_type or 'unknown'}",
                    url=download_url,
                    checksums=checksums,
                )
            ],
        )
    except Document.DoesNotExist:
        pass

    return 404, TEAErrorResponse(error="OBJECT_UNKNOWN")
