"""
TEA (Transparency Exchange API) endpoints.

Based on TEA OpenAPI Spec v0.3.0-beta.2.
All endpoints are public and workspace-scoped.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, TypeVar

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.db.models import Case, Prefetch, QuerySet, When
from django.http import HttpRequest
from django.utils import timezone
from libtea.models import ArtifactType as TEAArtifactType
from libtea.models import ChecksumAlgorithm, CollectionUpdateReasonType, ErrorType
from ninja import Query, Router

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM, ProductIdentifier
from sbomify.apps.sboms.utils import get_download_url_for_document, get_download_url_for_sbom
from sbomify.apps.tea.cache import TEA_TEAM_ATTR, hash_key_part, tea_cached
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
    TEABadRequestResponse,
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
from sbomify.apps.tea.utils import (
    _sanitize_for_log,
    get_artifact_mime_type,
    get_tea_artifact_type,
)
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Team

log = getLogger(__name__)

# auth=None: TEA endpoints are public per spec (workspace-scoped, no authentication)
router = Router(tags=["TEA"], auth=None, by_alias=True)

# TEA collection belongsTo constants
BELONGS_TO_PRODUCT_RELEASE = "PRODUCT_RELEASE"
BELONGS_TO_COMPONENT_RELEASE = "COMPONENT_RELEASE"


# =============================================================================
# Shared Helpers
# =============================================================================


_T = TypeVar("_T", bound=models.Model)


def _get_or_404(model_class: type[_T], **filters: object) -> _T | tuple[int, TEAErrorResponse]:
    """Get a model instance by UUID or return a (404, error) tuple.

    Catches both DoesNotExist and DjangoValidationError (raised when a
    malformed string is passed to a UUIDField lookup).
    """
    try:
        return model_class.objects.get(**filters)  # type: ignore[attr-defined, no-any-return]
    except (model_class.DoesNotExist, DjangoValidationError):  # type: ignore[attr-defined]
        return 404, TEAErrorResponse(error=ErrorType.OBJECT_UNKNOWN)


def _queryset_get_or_404(queryset: QuerySet[_T], **filters: object) -> _T | tuple[int, TEAErrorResponse]:
    """Like _get_or_404 but operates on an already-configured queryset."""
    try:
        return queryset.get(**filters)
    except (queryset.model.DoesNotExist, DjangoValidationError):  # type: ignore[attr-defined]
        return 404, TEAErrorResponse(error=ErrorType.OBJECT_UNKNOWN)


def _build_checksums(sha256_hash: str | None) -> list[TEAChecksum]:
    """Build checksum list from an optional SHA-256 hash."""
    if sha256_hash:
        return [TEAChecksum(algType=ChecksumAlgorithm.SHA_256, algValue=sha256_hash)]
    return []


_FORMAT_DISPLAY_NAMES = {"cyclonedx": "CycloneDX", "spdx": "SPDX"}


def _format_display_name(fmt: str) -> str:
    """Return a human-readable display name for an SBOM format."""
    return _FORMAT_DISPLAY_NAMES.get(fmt.lower(), fmt)


def _get_base_url(request: HttpRequest) -> str:
    """Get the base URL for download links, using the custom domain when available."""
    if getattr(request, "is_custom_domain", False):
        scheme = "https" if request.is_secure() else "http"
        return f"{scheme}://{request.get_host()}".rstrip("/")
    return settings.APP_BASE_URL.rstrip("/")


def _build_sbom_artifact(sbom: SBOM, base_url: str = "") -> TEAArtifact:
    """Build TEA Artifact from an SBOM."""
    return TEAArtifact(
        uuid=str(sbom.uuid),
        name=sbom.name,
        type=TEAArtifactType.BOM,
        distribution_types=None,
        formats=(
            TEAArtifactFormat(
                media_type=get_artifact_mime_type(sbom.format),
                description=f"{_format_display_name(sbom.format)} SBOM ({sbom.format_version})",
                url=get_download_url_for_sbom(sbom, base_url=base_url or settings.APP_BASE_URL),
                signature_url=sbom.signature_url,
                checksums=tuple(_build_checksums(sbom.sha256_hash)),
            ),
        ),
    )


def _build_document_artifact(doc: Document, base_url: str = "") -> TEAArtifact:
    """Build TEA Artifact from a Document."""
    return TEAArtifact(
        uuid=str(doc.uuid),
        name=doc.name,
        type=get_tea_artifact_type(doc.document_type),  # type: ignore[arg-type]
        distribution_types=None,
        formats=(
            TEAArtifactFormat(
                media_type=doc.content_type or "application/octet-stream",
                description=f"Document: {doc.document_type or 'unknown'}",
                url=get_download_url_for_document(doc, base_url=base_url or settings.APP_BASE_URL),
                signature_url=doc.signature_url,
                checksums=tuple(_build_checksums(doc.sha256_hash or doc.content_hash)),
            ),
        ),
    )


def _prefetch_releases(release_ids: list[str]) -> QuerySet[Release]:
    """Re-query releases by IDs with prefetch for N+1 prevention, preserving order."""
    if not release_ids:
        return Release.objects.none()

    ordering = Case(*[When(id=rid, then=pos) for pos, rid in enumerate(release_ids)])
    return (
        Release.objects.filter(id__in=release_ids)
        .select_related("product")
        .prefetch_related(
            Prefetch(
                "artifacts",
                queryset=ReleaseArtifact.objects.select_related("sbom__component", "document__component"),
            ),
            "product__identifiers",
        )
        .order_by(ordering)
    )


def _apply_identifier_filter(
    queryset: QuerySet[Any],
    team: Team,
    id_type: str,
    id_value: str,
    *,
    filter_releases: bool = False,
) -> QuerySet[Any]:
    """Apply identifier-based filtering to a product or release queryset.

    Args:
        queryset: Base queryset (Products or Releases)
        team: Workspace team
        id_type: TEA identifier type (e.g., "TEI", "PURL", "CPE")
        id_value: Identifier value to match
        filter_releases: If True, filters releases; if False, filters products
    """
    if id_type.upper() == "TEI":
        try:
            matching_releases = tea_tei_mapper(team, id_value)
            if filter_releases:
                return queryset.filter(id__in={r.id for r in matching_releases})
            return queryset.filter(id__in={r.product_id for r in matching_releases})
        except TEIParseError:
            log.warning("Invalid TEI filter (tei=%s)", _sanitize_for_log(id_value))
            return queryset.none()

    sbomify_types = TEA_IDENTIFIER_TYPE_MAPPING.get(id_type.upper())
    if not sbomify_types:
        log.warning("Unknown identifier type filter (idType=%s)", _sanitize_for_log(id_type))
        return queryset.none()

    if filter_releases:
        result = queryset.filter(
            product__identifiers__identifier_type__in=sbomify_types,
            product__identifiers__value=id_value,
        ).distinct()
    else:
        result = queryset.filter(
            identifiers__identifier_type__in=sbomify_types,
            identifiers__value=id_value,
        ).distinct()

    # PURL qualifier fallback: if no match and PURL has qualifiers, try two strategies:
    # 1) Canonicalized qualifier match — handles reordering/casing differences
    # 2) Base PURL fallback — strips qualifiers entirely
    # Check type/qualifiers before .exists() to avoid an unnecessary DB query for non-PURL filters.
    if id_type.upper() == "PURL" and "?" in id_value and not result.exists():
        from sbomify.apps.core.purl import (
            PURLParseError,
            canonicalize_qualifiers,
            extract_purl_qualifiers,
            parse_purl,
            strip_purl_qualifiers,
        )

        try:
            purl_parts = parse_purl(id_value)
            incoming_qualifiers = purl_parts.get("qualifiers", {})
            if incoming_qualifiers:
                base_value = strip_purl_qualifiers(id_value)

                # Step 1: canonicalized qualifier match
                canonical_incoming = canonicalize_qualifiers(incoming_qualifiers)
                qualified_candidates = ProductIdentifier.objects.filter(
                    team=team,
                    identifier_type__in=sbomify_types,
                    value__startswith=base_value + "?",
                    product__is_public=True,
                ).values_list("product_id", "value")
                matching_product_ids = {
                    product_id
                    for product_id, value in qualified_candidates
                    if extract_purl_qualifiers(value) == canonical_incoming
                }

                if matching_product_ids:
                    if filter_releases:
                        return queryset.filter(product_id__in=matching_product_ids).distinct()
                    return queryset.filter(id__in=matching_product_ids).distinct()

                # Step 2: base PURL fallback
                log.debug(
                    "PURL filter qualifier fallback: %s → %s",
                    _sanitize_for_log(id_value),
                    _sanitize_for_log(base_value),
                )
                if filter_releases:
                    return queryset.filter(
                        product__identifiers__identifier_type__in=sbomify_types,
                        product__identifiers__value=base_value,
                    ).distinct()
                return queryset.filter(
                    identifiers__identifier_type__in=sbomify_types,
                    identifiers__value=base_value,
                ).distinct()
        except PURLParseError:
            pass  # Invalid PURL — return the empty result

    return result


# =============================================================================
# Response Builders
# =============================================================================


def _build_product_response(product: Product) -> TEAProduct:
    """Build TEA Product response from sbomify Product."""
    return TEAProduct(
        uuid=str(product.uuid),
        name=product.name,
        identifiers=tuple(tea_identifier_mapper(product)),
    )


def _build_product_release_response(
    release: Release,
    include_components: bool = True,
) -> TEAProductRelease:
    """Build TEA Product Release response from sbomify Release."""
    components = []

    if include_components:
        # Map component_id -> sbom.uuid from release artifacts (public components only)
        release_artifacts = {
            artifact.sbom.component_id: str(artifact.sbom.uuid)
            for artifact in release.artifacts.all()
            if artifact.sbom
            and artifact.sbom.component_id
            and artifact.sbom.component.visibility == Component.Visibility.PUBLIC
        }

        product_components = Component.objects.filter(
            projects__products=release.product,
            team_id=release.product.team_id,
            visibility=Component.Visibility.PUBLIC,
        ).distinct()

        for component in product_components:
            component_ref = TEAComponentRef(
                uuid=str(component.uuid),
                release=release_artifacts.get(component.id),
            )
            components.append(component_ref)

    return TEAProductRelease(
        uuid=str(release.uuid),
        product=str(release.product.uuid),
        product_name=release.product.name,
        version=release.name,
        created_date=release.created_at,
        release_date=release.released_at,
        pre_release=release.is_prerelease,
        identifiers=tuple(tea_identifier_mapper(release.product)),
        components=tuple(components),
    )


def _build_component_response(component: Component) -> TEAComponent:
    """Build TEA Component response from sbomify Component."""
    return TEAComponent(
        uuid=str(component.uuid),
        name=component.name,
        identifiers=tuple(tea_component_identifier_mapper(component)),
    )


def _build_component_release_response(sbom: SBOM) -> TEARelease:
    """Build TEA Component Release response from sbomify SBOM."""
    version = sbom.version
    if not version:
        log.debug("SBOM %s has no version, using 'unknown'", sbom.uuid)
        version = "unknown"

    return TEARelease(
        uuid=str(sbom.uuid),
        component=str(sbom.component.uuid),
        component_name=sbom.component.name,
        version=version,
        created_date=sbom.created_at,
        release_date=sbom.created_at,  # SBOMs don't have separate release dates
        pre_release=False,  # SBOMs don't track pre-release status
        identifiers=tuple(tea_component_identifier_mapper(sbom.component)),  # type: ignore[arg-type]
        # TODO: TEA spec distributions field — sbomify doesn't model component
        # distributions (SBOMs ARE the component releases). Field is optional in spec.
        distributions=(),
    )


def _build_collection_response(
    release: Release,
    belongs_to: str,
    base_url: str = "",
) -> TEACollection:
    """Build TEA Collection response from sbomify Release artifacts."""
    artifacts = []
    for artifact in release.artifacts.select_related("sbom__component", "document__component").all():
        # Note: Only PUBLIC components are included in TEA responses (not GATED).
        # GATED components require user authentication/approval and are inappropriate
        # for unauthenticated TEA transparency endpoints.
        component = None
        if artifact.sbom:
            component = artifact.sbom.component
        elif artifact.document:
            component = artifact.document.component
        if component and component.visibility != Component.Visibility.PUBLIC:
            continue

        tea_artifact = _build_release_artifact(artifact, base_url=base_url)
        if tea_artifact:
            artifacts.append(tea_artifact)
        else:
            log.info("Skipping unresolvable artifact %s in collection for release %s", artifact.id, release.uuid)

    return TEACollection(
        uuid=str(release.uuid),
        version=release.collection_version,
        date=release.collection_updated_at or release.created_at,
        belongs_to=belongs_to,  # type: ignore[arg-type]
        update_reason=TEACollectionUpdateReason(
            type=release.collection_update_reason,  # type: ignore[arg-type]
            comment=None,
        ),
        artifacts=tuple(artifacts),
    )


def _build_release_artifact(artifact: ReleaseArtifact, base_url: str = "") -> TEAArtifact | None:
    """Build TEA Artifact from a ReleaseArtifact (SBOM or Document)."""
    if artifact.sbom:
        return _build_sbom_artifact(artifact.sbom, base_url=base_url)
    elif artifact.document:
        return _build_document_artifact(artifact.document, base_url=base_url)
    return None


def _build_sbom_collection_response(
    sbom: SBOM,
    belongs_to: str,
    base_url: str = "",
) -> TEACollection:
    """Build TEA Collection response from an SBOM and its sibling artifacts.

    Includes all SBOMs for the same component + version + qualifiers (same build
    variant) and documents for the same component + version, so both CycloneDX
    and SPDX formats appear in the same collection while different build variants
    (e.g., arch=arm64 vs arch=amd64) remain in separate collections.
    """
    artifacts: list[TEAArtifact] = []
    latest_date = sbom.created_at

    # Include SBOMs for same component + version + qualifiers (same build variant)
    sibling_sboms = list(
        SBOM.objects.filter(
            component=sbom.component,
            version=sbom.version,
            qualifiers=sbom.qualifiers,
            component__visibility=Component.Visibility.PUBLIC,
        )
        .select_related("component")
        .order_by("-created_at", "id")
    )
    for s in sibling_sboms:
        artifacts.append(_build_sbom_artifact(s, base_url=base_url))
        if s.created_at > latest_date:
            latest_date = s.created_at

    # Include documents for the same component + version
    sibling_docs = list(
        Document.objects.filter(
            component=sbom.component,
            version=sbom.version,
            component__visibility=Component.Visibility.PUBLIC,
        )
        .select_related("component")
        .order_by("-created_at", "id")
    )
    for doc in sibling_docs:
        artifacts.append(_build_document_artifact(doc, base_url=base_url))
        if doc.created_at > latest_date:
            latest_date = doc.created_at

    return TEACollection(
        uuid=str(sbom.uuid),
        version=1,
        date=latest_date,
        belongs_to=belongs_to,  # type: ignore[arg-type]
        update_reason=TEACollectionUpdateReason(
            type=CollectionUpdateReasonType.INITIAL_RELEASE,
            comment="Initial collection",
        ),
        artifacts=tuple(artifacts),
    )


# =============================================================================
# Discovery Endpoints
# =============================================================================


@router.get(
    "/discovery",
    response={200: list[TEADiscoveryInfo], 400: TEABadRequestResponse, 404: TEAErrorResponse},
    summary="Discover TEA resources by TEI",
    description="Discovery endpoint which resolves TEI into product release UUIDs.",
)
@tea_cached(lambda tei, **_: ("discovery", hash_key_part(tei)))
def discovery(
    request: HttpRequest,
    tei: str = Query(..., max_length=2048, description="Transparency Exchange Identifier (TEI) - URL-encoded string"),  # type: ignore[type-arg]
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key (for non-custom-domain access)"),  # type: ignore[type-arg]
) -> Any:
    """Resolve TEI to product releases."""
    team = getattr(request, TEA_TEAM_ATTR)

    try:
        releases = tea_tei_mapper(team, tei)
    except TEIParseError:
        log.warning("Discovery: invalid TEI format (tei=%s)", _sanitize_for_log(tei))
        return 400, TEABadRequestResponse(error="Invalid TEI format")

    if not releases:
        return 404, TEAErrorResponse(error=ErrorType.OBJECT_UNKNOWN)

    # Build discovery response for each release
    server_url = build_tea_server_url(team, workspace_key, request=request)

    results = [
        TEADiscoveryInfo(
            product_release_uuid=str(release.uuid),
            servers=(
                TEAServerInfo(
                    root_url=server_url,
                    versions=(TEA_API_VERSION,),
                    priority=1.0,
                ),
            ),
        )
        for release in releases
    ]

    return 200, results


# =============================================================================
# Product Endpoints
# =============================================================================


@router.get(
    "/products",
    response={200: TEAPaginatedProductResponse, 400: TEABadRequestResponse},
    summary="List products",
    description="Returns a list of TEA products. Can be filtered by identifier.",
)
@tea_cached(
    lambda pageOffset=0, pageSize=100, idType=None, idValue=None, **_: (
        "products",
        f"page={pageOffset}&size={pageSize}&id_type={idType}&id_value={hash_key_part(idValue) if idValue else None}",
    )
)
def list_products(
    request: HttpRequest,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
    idType: str | None = Query(None, max_length=50, description="Type of identifier to filter by"),  # type: ignore[type-arg]
    idValue: str | None = Query(None, max_length=2048, description="Identifier value to filter by"),  # type: ignore[type-arg]
    pageOffset: int = Query(0, ge=0, description="Pagination offset"),  # type: ignore[type-arg]
    pageSize: int = Query(100, ge=1, le=1000, description="Page size"),  # type: ignore[type-arg]
) -> Any:
    """List all products in a workspace."""
    team = getattr(request, TEA_TEAM_ATTR)

    # Base queryset - only public products, prefetch identifiers for efficiency
    products = Product.objects.filter(team=team, is_public=True).prefetch_related("identifiers").order_by("id")

    # Filter by identifier if provided
    if idType and idValue:
        products = _apply_identifier_filter(products, team, idType, idValue)

    # Get total count
    total = products.count()

    # Apply pagination
    products = products[pageOffset : pageOffset + pageSize]

    # Build response
    results = [_build_product_response(p) for p in products]

    return (
        200,
        TEAPaginatedProductResponse(
            timestamp=timezone.now(),
            page_start_index=pageOffset,
            page_size=pageSize,
            total_results=total,
            results=tuple(results),
        ),
    )


@router.get(
    "/product/{uuid}",
    response={200: TEAProduct, 400: TEABadRequestResponse, 404: TEAErrorResponse},
    summary="Get product by UUID",
    description="Get a TEA Product by UUID.",
)
@tea_cached(lambda uuid, **_: ("product", uuid))
def get_product(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    """Get a single product by UUID."""
    team = getattr(request, TEA_TEAM_ATTR)

    result = _queryset_get_or_404(Product.objects.prefetch_related("identifiers"), uuid=uuid, team=team, is_public=True)
    if isinstance(result, tuple):
        return result

    return 200, _build_product_response(result)


@router.get(
    "/product/{uuid}/releases",
    response={200: TEAPaginatedProductReleaseResponse, 400: TEABadRequestResponse, 404: TEAErrorResponse},
    summary="Get product releases",
    description="Get releases of the product.",
)
@tea_cached(
    lambda uuid, pageOffset=0, pageSize=100, **_: ("product", uuid, "releases", f"page={pageOffset}&size={pageSize}")
)
def get_product_releases(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
    pageOffset: int = Query(0, ge=0, description="Pagination offset"),  # type: ignore[type-arg]
    pageSize: int = Query(100, ge=1, le=1000, description="Page size"),  # type: ignore[type-arg]
) -> Any:
    """Get releases for a product."""
    team = getattr(request, TEA_TEAM_ATTR)

    product = _get_or_404(Product, uuid=uuid, team=team, is_public=True)
    if isinstance(product, tuple):
        return product

    # Single-product scope: exclude "latest" only when this product has versioned releases.
    base_qs = product.releases.order_by("-created_at", "id")
    non_latest = base_qs.exclude(is_latest=True)
    all_releases = non_latest if non_latest.exists() else base_qs
    total = all_releases.count()

    # Apply pagination, then prefetch for N+1 prevention (preserving order)
    paginated = all_releases[pageOffset : pageOffset + pageSize]
    release_ids = [r.id for r in paginated]
    releases = _prefetch_releases(release_ids)

    results = [_build_product_release_response(r) for r in releases]

    return (
        200,
        TEAPaginatedProductReleaseResponse(
            timestamp=timezone.now(),
            page_start_index=pageOffset,
            page_size=pageSize,
            total_results=total,
            results=tuple(results),
        ),
    )


# =============================================================================
# Product Release Endpoints
# =============================================================================


@router.get(
    "/productReleases",
    response={200: TEAPaginatedProductReleaseResponse, 400: TEABadRequestResponse},
    summary="Query product releases",
    description="Returns a list of TEA product releases. Can be filtered by identifier.",
)
@tea_cached(
    lambda pageOffset=0, pageSize=100, idType=None, idValue=None, **_: (
        "product_releases",
        f"page={pageOffset}&size={pageSize}&id_type={idType}&id_value={hash_key_part(idValue) if idValue else None}",
    )
)
def query_product_releases(
    request: HttpRequest,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
    idType: str | None = Query(None, max_length=50, description="Type of identifier to filter by"),  # type: ignore[type-arg]
    idValue: str | None = Query(None, max_length=2048, description="Identifier value to filter by"),  # type: ignore[type-arg]
    pageOffset: int = Query(0, ge=0, description="Pagination offset"),  # type: ignore[type-arg]
    pageSize: int = Query(100, ge=1, le=1000, description="Page size"),  # type: ignore[type-arg]
) -> Any:
    """Query product releases."""
    team = getattr(request, TEA_TEAM_ATTR)

    # Base queryset - only releases from public products, with prefetch for efficiency.
    # Per-product: exclude "latest" only when that product has versioned releases.
    products_with_versioned = (
        Release.objects.filter(product__team=team, product__is_public=True, is_latest=False)
        .values_list("product_id", flat=True)
        .distinct()
    )
    releases = (
        Release.objects.filter(product__team=team, product__is_public=True)
        .exclude(is_latest=True, product_id__in=products_with_versioned)
        .select_related("product")
        .prefetch_related("product__identifiers")
        .order_by("-created_at", "id")
    )

    # Filter by identifier if provided
    if idType and idValue:
        releases = _apply_identifier_filter(releases, team, idType, idValue, filter_releases=True)

    total = releases.count()
    paginated = releases[pageOffset : pageOffset + pageSize]

    # Re-query with prefetch for N+1 prevention (preserving order)
    release_ids = [r.id for r in paginated]
    paginated = _prefetch_releases(release_ids)

    results = [_build_product_release_response(r) for r in paginated]

    return (
        200,
        TEAPaginatedProductReleaseResponse(
            timestamp=timezone.now(),
            page_start_index=pageOffset,
            page_size=pageSize,
            total_results=total,
            results=tuple(results),
        ),
    )


@router.get(
    "/productRelease/{uuid}",
    response={200: TEAProductRelease, 400: TEABadRequestResponse, 404: TEAErrorResponse},
    summary="Get product release by UUID",
    description="Get a TEA Product Release.",
)
@tea_cached(lambda uuid, **_: ("product_release", uuid))
def get_product_release(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    """Get a single product release by UUID."""
    team = getattr(request, TEA_TEAM_ATTR)

    release = _queryset_get_or_404(
        Release.objects.select_related("product").prefetch_related(
            Prefetch(
                "artifacts",
                queryset=ReleaseArtifact.objects.select_related("sbom__component", "document__component"),
            ),
            "product__identifiers",
        ),
        uuid=uuid,
        product__team=team,
        product__is_public=True,
    )
    if isinstance(release, tuple):
        return release

    return 200, _build_product_release_response(release)


@router.get(
    "/productRelease/{uuid}/collection/latest",
    response={200: TEACollection, 400: TEABadRequestResponse, 404: TEAErrorResponse},
    summary="Get latest collection for product release",
    description="Get the latest TEA Collection belonging to the TEA Product Release.",
)
@tea_cached(lambda uuid, **_: ("product_release", uuid, "collection", "latest"))
def get_product_release_latest_collection(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    """Get the latest collection for a product release."""
    team = getattr(request, TEA_TEAM_ATTR)

    release = _get_or_404(Release, uuid=uuid, product__team=team, product__is_public=True)
    if isinstance(release, tuple):
        return release

    return 200, _build_collection_response(release, BELONGS_TO_PRODUCT_RELEASE, base_url=_get_base_url(request))


@router.get(
    "/productRelease/{uuid}/collections",
    response={200: list[TEACollection], 400: TEABadRequestResponse, 404: TEAErrorResponse},
    summary="Get all collections for product release",
    description="Get the TEA Collections belonging to the TEA Product Release.",
)
@tea_cached(lambda uuid, **_: ("product_release", uuid, "collections"))
def get_product_release_collections(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    """Get all collections for a product release."""
    team = getattr(request, TEA_TEAM_ATTR)

    release = _get_or_404(Release, uuid=uuid, product__team=team, product__is_public=True)
    if isinstance(release, tuple):
        return release

    # We only have one collection version per release currently
    collection = _build_collection_response(release, BELONGS_TO_PRODUCT_RELEASE, base_url=_get_base_url(request))
    return 200, [collection]


@router.get(
    "/productRelease/{uuid}/collection/{version}",
    response={200: TEACollection, 400: TEABadRequestResponse, 404: TEAErrorResponse},
    summary="Get specific collection version for product release",
    description="Get a specific Collection (by version) for a TEA Product Release.",
)
@tea_cached(lambda uuid, version, **_: ("product_release", uuid, "collection", str(version)))
def get_product_release_collection_version(
    request: HttpRequest,
    uuid: str,
    version: int,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    """Get a specific collection version for a product release."""
    team = getattr(request, TEA_TEAM_ATTR)

    release = _get_or_404(Release, uuid=uuid, product__team=team, product__is_public=True)
    if isinstance(release, tuple):
        return release

    # Historical collection snapshots are not stored — only the current version is available.
    # Reject version <= 0 and any version that isn't the current one.
    if version < 1 or version != release.collection_version:
        return 404, TEAErrorResponse(error=ErrorType.OBJECT_UNKNOWN)

    return 200, _build_collection_response(release, BELONGS_TO_PRODUCT_RELEASE, base_url=_get_base_url(request))


# =============================================================================
# Component Endpoints
# =============================================================================


@router.get(
    "/component/{uuid}",
    response={200: TEAComponent, 400: TEABadRequestResponse, 404: TEAErrorResponse},
    summary="Get component by UUID",
    description="Get a TEA Component.",
)
@tea_cached(lambda uuid, **_: ("component", uuid))
def get_component(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    """Get a single component by UUID."""
    team = getattr(request, TEA_TEAM_ATTR)

    component = _queryset_get_or_404(
        Component.objects.prefetch_related("identifiers"),
        uuid=uuid,
        team=team,
        visibility=Component.Visibility.PUBLIC,
    )
    if isinstance(component, tuple):
        return component

    return 200, _build_component_response(component)


@router.get(
    "/component/{uuid}/releases",
    response={200: list[TEARelease], 400: TEABadRequestResponse, 404: TEAErrorResponse},
    summary="Get component releases",
    description="Get releases of the component.",
)
@tea_cached(lambda uuid, **_: ("component", uuid, "releases"))
def get_component_releases(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    """Get releases (SBOMs) for a component."""
    team = getattr(request, TEA_TEAM_ATTR)

    component = _get_or_404(Component, uuid=uuid, team=team, visibility=Component.Visibility.PUBLIC)
    if isinstance(component, tuple):
        return component

    # Get all SBOMs for this component, deduplicated by version.
    # Multiple SBOMs for the same version (e.g., CycloneDX + SPDX) represent
    # different artifact formats, not separate releases in the TEA model.
    sboms = (
        component.sbom_set.select_related("component")
        .prefetch_related("component__identifiers")
        .order_by("-created_at", "id")
    )
    seen: set[tuple[str, str]] = set()
    results = []
    for sbom in sboms:
        version_key = sbom.version or "unknown"
        qualifiers_key = json.dumps(sbom.qualifiers or {}, sort_keys=True)
        dedup_key = (version_key, qualifiers_key)
        if dedup_key not in seen:
            seen.add(dedup_key)
            results.append(_build_component_release_response(sbom))

    return 200, results


# =============================================================================
# Component Release Endpoints
# =============================================================================


@router.get(
    "/componentRelease/{uuid}",
    response={200: TEAComponentReleaseWithCollection, 400: TEABadRequestResponse, 404: TEAErrorResponse},
    summary="Get component release with collection",
    description="Get the TEA Component Release with its latest collection.",
)
@tea_cached(lambda uuid, **_: ("component_release", uuid))
def get_component_release(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    """Get a component release (SBOM) with its collection."""
    team = getattr(request, TEA_TEAM_ATTR)

    sbom = _queryset_get_or_404(
        SBOM.objects.select_related("component"),
        uuid=uuid,
        component__team=team,
        component__visibility=Component.Visibility.PUBLIC,
    )
    if isinstance(sbom, tuple):
        return sbom

    release = _build_component_release_response(sbom)
    base_url = _get_base_url(request)
    collection = _build_sbom_collection_response(sbom, BELONGS_TO_COMPONENT_RELEASE, base_url=base_url)

    return (
        200,
        TEAComponentReleaseWithCollection(
            release=release,
            latest_collection=collection,
        ),
    )


@router.get(
    "/componentRelease/{uuid}/collection/latest",
    response={200: TEACollection, 400: TEABadRequestResponse, 404: TEAErrorResponse},
    summary="Get latest collection for component release",
    description="Get the latest TEA Collection belonging to the TEA Component Release.",
)
@tea_cached(lambda uuid, **_: ("component_release", uuid, "collection", "latest"))
def get_component_release_latest_collection(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    """Get the latest collection for a component release (SBOM)."""
    team = getattr(request, TEA_TEAM_ATTR)

    sbom = _queryset_get_or_404(
        SBOM.objects.select_related("component"),
        uuid=uuid,
        component__team=team,
        component__visibility=Component.Visibility.PUBLIC,
    )
    if isinstance(sbom, tuple):
        return sbom

    return 200, _build_sbom_collection_response(sbom, BELONGS_TO_COMPONENT_RELEASE, base_url=_get_base_url(request))


@router.get(
    "/componentRelease/{uuid}/collections",
    response={200: list[TEACollection], 400: TEABadRequestResponse, 404: TEAErrorResponse},
    summary="Get all collections for component release",
    description="Get the TEA Collections belonging to the TEA Component Release.",
)
@tea_cached(lambda uuid, **_: ("component_release", uuid, "collections"))
def get_component_release_collections(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    """Get all collections for a component release (SBOM)."""
    team = getattr(request, TEA_TEAM_ATTR)

    sbom = _queryset_get_or_404(
        SBOM.objects.select_related("component"),
        uuid=uuid,
        component__team=team,
        component__visibility=Component.Visibility.PUBLIC,
    )
    if isinstance(sbom, tuple):
        return sbom

    # We only have one collection version per SBOM currently
    collection = _build_sbom_collection_response(sbom, BELONGS_TO_COMPONENT_RELEASE, base_url=_get_base_url(request))
    return 200, [collection]


@router.get(
    "/componentRelease/{uuid}/collection/{version}",
    response={200: TEACollection, 400: TEABadRequestResponse, 404: TEAErrorResponse},
    summary="Get specific collection version for component release",
    description="Get a specific Collection (by version) for a TEA Component Release.",
)
@tea_cached(lambda uuid, version, **_: ("component_release", uuid, "collection", str(version)))
def get_component_release_collection_version(
    request: HttpRequest,
    uuid: str,
    version: int,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    """Get a specific collection version for a component release (SBOM)."""
    team = getattr(request, TEA_TEAM_ATTR)

    sbom = _queryset_get_or_404(
        SBOM.objects.select_related("component"),
        uuid=uuid,
        component__team=team,
        component__visibility=Component.Visibility.PUBLIC,
    )
    if isinstance(sbom, tuple):
        return sbom

    # Component releases (SBOMs) always have exactly one collection version (v1).
    # Historical snapshots are not stored — only the current version is available.
    if version != 1:
        return 404, TEAErrorResponse(error=ErrorType.OBJECT_UNKNOWN)

    return 200, _build_sbom_collection_response(sbom, BELONGS_TO_COMPONENT_RELEASE, base_url=_get_base_url(request))


# =============================================================================
# Artifact Endpoints
# =============================================================================


@router.get(
    "/artifact/{uuid}",
    response={200: TEAArtifact, 400: TEABadRequestResponse, 404: TEAErrorResponse},
    summary="Get artifact by UUID",
    description="Get metadata for specific TEA Artifact.",
)
@tea_cached(lambda uuid, **_: ("artifact", uuid))
def get_artifact(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    """Get artifact metadata by UUID."""
    team = getattr(request, TEA_TEAM_ATTR)

    base_url = _get_base_url(request)
    artifact_filters = dict(uuid=uuid, component__team=team, component__visibility=Component.Visibility.PUBLIC)

    # Try to find as SBOM first
    sbom = _queryset_get_or_404(SBOM.objects.select_related("component"), **artifact_filters)
    if not isinstance(sbom, tuple):
        return 200, _build_sbom_artifact(sbom, base_url=base_url)

    # Fall back to Document
    document = _queryset_get_or_404(Document.objects.select_related("component"), **artifact_filters)
    if not isinstance(document, tuple):
        return 200, _build_document_artifact(document, base_url=base_url)

    return 404, TEAErrorResponse(error=ErrorType.OBJECT_UNKNOWN)
