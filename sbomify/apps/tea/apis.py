"""
TEA (Transparency Exchange API) endpoints.

Based on TEA OpenAPI Spec v1.0.0.
All endpoints are public and workspace-scoped.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from functools import wraps
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from django.db.models import Case, F, OrderBy, Prefetch, QuerySet, When
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from libtea.models import ArtifactType as TEAArtifactType
from libtea.models import ChecksumAlgorithm, CollectionBelongsTo, CollectionUpdateReasonType, ErrorType
from ninja import Query, Router

from sbomify.apps.core.models import (
    Component,
    ComponentRelease,
    ComponentReleaseArtifact,
    Product,
    Release,
    ReleaseArtifact,
)
from sbomify.apps.core.services.cle import (
    get_cle_document,
    get_component_cle_document,
    get_component_release_cle_document,
    get_release_cle_document,
)
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.utils import get_download_url_for_document, get_download_url_for_sbom
from sbomify.apps.tea.cache import TEA_TEAM_ATTR, hash_key_part, tea_cached
from sbomify.apps.tea.mappers import (
    TEA_API_VERSION,
    TEA_IDENTIFIER_TYPE_MAPPING,
    TEIParseError,
    build_tea_server_url,
    tea_identifier_mapper,
    tea_purl_mapper,
    tea_tei_mapper,
)
from sbomify.apps.tea.schemas import (
    TEACLE,
    TEAArtifact,
    TEABadRequestResponse,
    TEAChecksum,
    TEACollection,
    TEAComponent,
    TEAComponentRef,
    TEAComponentReleaseWithCollection,
    TEADiscoveryInfo,
    TEAErrorResponse,
    TEAPaginatedCollectionResponse,
    TEAPaginatedComponentReleaseResponse,
    TEAPaginatedComponentResponse,
    TEAPaginatedProductReleaseResponse,
    TEAPaginatedProductResponse,
    TEAProduct,
    TEAProductRelease,
    TEAProductReleaseWithCollection,
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
    from libtea.models import CLE

    from sbomify.apps.teams.models import Workspace

log = getLogger(__name__)

# auth=None: TEA endpoints are public per spec (workspace-scoped, no authentication).
# TEA 1.0.0 responses carry no null and no empty default the server did not set.
router = Router(tags=["TEA"], auth=None, by_alias=True, exclude_none=True, exclude_unset=True)

# TEA collection belongsTo constants
BELONGS_TO_PRODUCT_RELEASE = CollectionBelongsTo.PRODUCT_RELEASE
BELONGS_TO_COMPONENT_RELEASE = CollectionBelongsTo.COMPONENT_RELEASE


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


def _artifact(fields: dict[str, Any], fmt: dict[str, Any], created_at: datetime) -> TEAArtifact:
    """Build an artifact with its one format.

    sbomify never changes an uploaded artifact, so each one has a single revision.
    TEA 1.0.0 publishes a url only with a checksum; without one, a client fetches
    the format from the download endpoint, which redirects to the url.
    """
    if not fmt["checksums"]:
        fmt = {key: value for key, value in fmt.items() if key not in ("url", "checksums")}
    return TEAArtifact.model_validate({**fields, "version": 1, "created_date": created_at, "formats": (fmt,)})


def _sbom_format(sbom: SBOM, base_url: str = "") -> dict[str, Any]:
    """The one format of an SBOM-model artifact, url and checksum included."""
    kind = SBOM.BomType(sbom.bom_type).label if sbom.bom_type in SBOM.BomType.values else "SBOM"
    return {
        "media_type": get_artifact_mime_type(sbom.format),
        "description": f"{_format_display_name(sbom.format)} {kind} ({sbom.format_version})",
        "url": get_download_url_for_sbom(sbom, base_url=base_url or settings.APP_BASE_URL),
        "signature_url": sbom.signature_url,
        "checksums": tuple(_build_checksums(sbom.sha256_hash)),
    }


def _document_format(doc: Document, base_url: str = "") -> dict[str, Any]:
    """The one format of a document, url and checksum included."""
    return {
        "media_type": doc.content_type or "application/octet-stream",
        "description": f"Document: {doc.document_type or 'unknown'}",
        "url": get_download_url_for_document(doc, base_url=base_url or settings.APP_BASE_URL),
        "signature_url": doc.signature_url,
        "checksums": tuple(_build_checksums(doc.sha256_hash or doc.content_hash)),
    }


def _build_sbom_artifact(sbom: SBOM, base_url: str = "") -> TEAArtifact:
    """Build TEA Artifact from an SBOM-model artifact of any bom_type.

    TEA's artifact-type vocabulary has no dedicated CBOM entry, so a CBOM (or
    any other xBOM) serves as a generic BOM with its kind named in the format
    description. A VEX maps to VULNERABILITIES, TEA's type for VDR/VEX content.
    """
    artifact_type = TEAArtifactType.VULNERABILITIES if sbom.bom_type == SBOM.BomType.VEX else TEAArtifactType.BOM
    return _artifact(
        {"uuid": str(sbom.uuid), "name": sbom.name, "type": artifact_type},
        _sbom_format(sbom, base_url),
        sbom.created_at,
    )


def _build_document_artifact(doc: Document, base_url: str = "") -> TEAArtifact:
    """Build TEA Artifact from a Document."""
    return _artifact(
        {"uuid": str(doc.uuid), "name": doc.name, "type": get_tea_artifact_type(doc.document_type)},
        _document_format(doc, base_url),
        doc.created_at,
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
    team: Workspace,
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
        return queryset.filter(
            product__identifiers__identifier_type__in=sbomify_types,
            product__identifiers__value=id_value,
        ).distinct()
    return queryset.filter(
        identifiers__identifier_type__in=sbomify_types,
        identifiers__value=id_value,
    ).distinct()


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
        # Map component_id -> ComponentRelease.uuid via junction table (public components only)
        artifact_sboms = [
            artifact.sbom
            for artifact in release.artifacts.filter(
                sbom__bom_type__in=(SBOM.BomType.SBOM, SBOM.BomType.CBOM, SBOM.BomType.VEX)
            ).select_related("sbom__component")
            if artifact.sbom
            and artifact.sbom.component_id
            and artifact.sbom.component.visibility == Component.Visibility.PUBLIC
        ]
        cr_uuid_by_component: dict[str, str] = {}
        if artifact_sboms:
            sbom_ids = [sbom.id for sbom in artifact_sboms]
            # Order newest-first; only set on first-seen so most recent wins per component
            for cra in (
                ComponentReleaseArtifact.objects.filter(sbom_id__in=sbom_ids)
                .select_related("component_release", "sbom")
                .order_by("-created_at", "-pk")
            ):
                component_id = cra.sbom.component_id
                if component_id not in cr_uuid_by_component:
                    cr_uuid_by_component[component_id] = str(cra.component_release.uuid)

        product_components = Component.objects.filter(
            products=release.product,
            team_id=release.product.team_id,
            visibility=Component.Visibility.PUBLIC,
        ).distinct()

        for component in product_components:
            component_ref = TEAComponentRef(
                uuid=str(component.uuid),
                release=cr_uuid_by_component.get(component.id),
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
        identifiers=(),
    )


def _build_component_release_response(component_release: ComponentRelease) -> TEARelease:
    """Build TEA Component Release response from a ComponentRelease."""
    component = component_release.component
    version = component_release.version
    if not version:
        log.debug("ComponentRelease %s has no version, using 'unknown'", component_release.uuid)
        version = "unknown"

    return TEARelease(
        uuid=str(component_release.uuid),
        component=str(component.uuid),
        component_name=component.name,
        version=version,
        created_date=component_release.created_at,
        # TODO: Add released_at field to ComponentRelease for distinct release date
        release_date=component_release.created_at,
        # TODO: Add is_prerelease field or derive from semver pre-release suffix
        pre_release=False,
        identifiers=(),
        distributions=(),
    )


def _build_collection_response(
    release: Release,
    belongs_to: CollectionBelongsTo,
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

    return TEACollection.model_validate(
        {
            "uuid": str(release.uuid),
            "version": release.collection_version,
            "created_date": release.collection_updated_at or release.created_at,
            "belongs_to": belongs_to,
            "update_reason": {"type": CollectionUpdateReasonType(release.collection_update_reason), "comment": None},
            "artifacts": tuple(artifacts),
        },
    )


def _build_release_artifact(artifact: ReleaseArtifact, base_url: str = "") -> TEAArtifact | None:
    """Build TEA Artifact from a ReleaseArtifact (SBOM or Document)."""
    if artifact.sbom:
        return _build_sbom_artifact(artifact.sbom, base_url=base_url)
    elif artifact.document:
        return _build_document_artifact(artifact.document, base_url=base_url)
    return None


def _build_component_release_collection_response(
    component_release: ComponentRelease,
    belongs_to: CollectionBelongsTo,
    base_url: str = "",
) -> TEACollection:
    """Build TEA Collection response from a ComponentRelease and its artifacts.

    SBOMs come from the ComponentReleaseArtifact junction table.
    Documents are still computed from the component (not yet in junction table).
    """
    artifacts: list[TEAArtifact] = []

    # Track the latest artifact date across SBOMs and documents so the collection
    # date reflects the newest included artifact, not just SBOM link changes.
    latest_date = component_release.collection_updated_at or component_release.created_at

    # SBOMs from junction table (newest-first, consistent with document ordering).
    # Filter by component as defense-in-depth against mis-linked artifacts.
    for cra in (
        component_release.artifacts.filter(sbom__component=component_release.component)
        .select_related("sbom__component")
        .order_by("-created_at", "pk")
    ):
        sbom = cra.sbom
        if sbom.component.visibility != Component.Visibility.PUBLIC:
            continue
        artifacts.append(_build_sbom_artifact(sbom, base_url=base_url))
        if cra.created_at and cra.created_at > latest_date:
            latest_date = cra.created_at

    # Documents — still computed from component (deferred from junction table).
    # TODO: Documents are not filtered by PURL qualifiers — all ComponentReleases for
    # the same component+version share the same documents. This is acceptable because
    # Documents don't have qualifier metadata, but should be revisited if that changes.
    # TODO: Document add/remove does not bump collection_version because documents
    # are not yet in the junction table. Once a DocumentArtifact junction model is
    # added, document changes should also bump collection_version.
    sibling_docs = (
        Document.objects.filter(
            component=component_release.component,
            version=component_release.version,
            component__visibility=Component.Visibility.PUBLIC,
        )
        .select_related("component")
        .order_by("-created_at", "id")
    )

    for doc in sibling_docs:
        artifacts.append(_build_document_artifact(doc, base_url=base_url))
        if doc.created_at and doc.created_at > latest_date:
            latest_date = doc.created_at

    return TEACollection.model_validate(
        {
            "uuid": str(component_release.uuid),
            "version": component_release.collection_version,
            "created_date": latest_date,
            "belongs_to": belongs_to,
            "update_reason": {
                "type": CollectionUpdateReasonType(component_release.collection_update_reason),
                "comment": None,
            },
            "artifacts": tuple(artifacts),
        },
    )


def _discovery_results(
    request: HttpRequest, team: Workspace, workspace_key: str | None, releases: list[Release]
) -> list[TEADiscoveryInfo]:
    """One discovery entry per release, each naming this server and the TEA versions it serves."""
    server = TEAServerInfo(
        root_url=build_tea_server_url(team, workspace_key, request=request),
        versions=(TEA_API_VERSION,),
        priority=1.0,
    )
    return [TEADiscoveryInfo(product_release_uuid=str(release.uuid), servers=(server,)) for release in releases]


def _find_artifact(team: Workspace, uuid: str) -> SBOM | Document | None:
    """Find a public SBOM, or failing that a public document, by its UUID."""
    artifact_filters = dict(uuid=uuid, component__team=team, component__visibility=Component.Visibility.PUBLIC)
    sbom = _queryset_get_or_404(SBOM.objects.select_related("component"), **artifact_filters)
    if not isinstance(sbom, tuple):
        return sbom
    document = _queryset_get_or_404(Document.objects.select_related("component"), **artifact_filters)
    return None if isinstance(document, tuple) else document


def _build_artifact(found: SBOM | Document, base_url: str) -> TEAArtifact:
    if isinstance(found, SBOM):
        return _build_sbom_artifact(found, base_url=base_url)
    return _build_document_artifact(found, base_url=base_url)


NOT_FOUND = (404, TEAErrorResponse(error=ErrorType.OBJECT_UNKNOWN))
_PAGE_SALT = "sbomify.tea.v1.page-token"

IdType = Literal["CPE", "TEI", "PURL", "COMPLIANCE_DOCUMENT"]
SortOrder = Literal["asc", "desc"]
ReleaseSortField = Literal["createdDate", "releaseDate", "version"]


def _invalid(message: str, error: ErrorType = ErrorType.INVALID_REQUEST) -> tuple[int, TEAErrorResponse]:
    return 400, TEAErrorResponse(error=error, message=message)


def _cached(key_builder: Callable[..., tuple[str, ...]]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """``tea_cached``, keyed under the TEA version too, with its 400 body in the TEA error shape.

    The version keeps a response the 0.4.0 API cached under the same names from being served here.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        cached = tea_cached(lambda **kwargs: (TEA_API_VERSION, *key_builder(**kwargs)))(func)

        @wraps(func)
        def wrapper(request: HttpRequest, **kwargs: Any) -> Any:
            response = cached(request, **kwargs)
            if isinstance(response, tuple) and isinstance(response[1], TEABadRequestResponse):
                return _invalid(response[1].error)
            return response

        return wrapper

    return decorator


def _page_key(name: str) -> Callable[..., tuple[str, ...]]:
    """Cache key for a paginated endpoint: every parameter that changes its response."""

    def key(
        uuid: str = "",
        pageSize: int = 25,
        pageToken: str | None = None,
        sortField: str = "",
        sortOrder: str = "asc",
        idType: str | None = None,
        idValue: str | None = None,
        **_: Any,
    ) -> tuple[str, ...]:
        token = hash_key_part(pageToken) if pageToken is not None else ""
        id_value = hash_key_part(idValue) if idValue else ""
        return (name, uuid, f"size={pageSize}&token={token}&sort={sortField}:{sortOrder}&id={idType}:{id_value}")

    return key


def _ordered(queryset: QuerySet[Any], fields: Sequence[str], sort_order: SortOrder) -> QuerySet[Any]:
    """Order by ``fields``, then ``uuid``, all in ``sort_order``.

    A missing value sorts after the others ascending and before them descending,
    as TEA 1.0.0 asks of ``releaseDate``.
    """
    expressions = [F(field) for field in (*fields, "uuid")]
    ordering: list[OrderBy] = [
        e.desc(nulls_first=True) if sort_order == "desc" else e.asc(nulls_last=True) for e in expressions
    ]
    return queryset.order_by(*ordering)


def _page(
    request: HttpRequest,
    page_model: type[Any],
    rows: QuerySet[Any] | Sequence[Any],
    build: Callable[[list[Any]], list[Any]],
    *,
    page_size: int,
    page_token: str | None,
    state: Sequence[str | None],
) -> tuple[int, Any]:
    """Answer one page of ``rows``.

    The page token is signed and carries the next offset plus ``state``, the
    request path and every parameter that selects or orders the results, so a
    token used with a different query is rejected, as TEA 1.0.0 requires.
    """
    query = [request.path, *state]
    offset = 0
    if page_token is not None:
        try:
            token = signing.loads(page_token, salt=_PAGE_SALT)
        except signing.BadSignature:
            return _invalid("pageToken is not valid", ErrorType.INVALID_PAGE_TOKEN)
        if token.get("query") != query:
            return _invalid("pageToken belongs to a different query", ErrorType.INVALID_PAGE_TOKEN)
        offset = token["offset"]

    window = list(rows[offset : offset + page_size + 1])
    page: dict[str, Any] = {"has_next": len(window) > page_size, "results": build(window[:page_size])}
    if page["has_next"]:
        page["next_page_token"] = signing.dumps({"offset": offset + page_size, "query": query}, salt=_PAGE_SALT)
    return 200, page_model.model_validate(page)


def _cle(result: ServiceResult[CLE], uuid: str) -> tuple[int, Any]:
    if not result.ok:
        if result.status_code == 500:
            log.error("CLE conversion error for %s: %s", uuid, result.error)
        return NOT_FOUND
    return 200, result.value


def _public_releases(product: Product) -> QuerySet[Release]:
    """A product's releases, leaving out the "latest" alias when the product has versioned ones."""
    releases = product.releases.all()
    non_latest = releases.exclude(is_latest=True)
    return non_latest if non_latest.exists() else releases


def _release_rows(releases: list[Release]) -> list[Any]:
    return [_build_product_release_response(r) for r in _prefetch_releases([r.id for r in releases])]


_RELEASE_SORT = {"createdDate": "created_at", "releaseDate": "released_at", "version": "name"}
# A component release records no separate release date, and reports its creation date as one.
_COMPONENT_RELEASE_SORT = {"createdDate": "created_at", "releaseDate": "created_at", "version": "version"}


# =============================================================================
# Discovery
# =============================================================================


@router.get(
    "/discovery",
    response={200: list[TEADiscoveryInfo], 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Resolve an identifier to TEA Product Releases",
    description="Resolves a TEI, in either the tei:// or the urn:tei: form, or a PURL to product release UUIDs. "
    "Give exactly one of tei and purl.",
)
@_cached(lambda tei=None, purl=None, **_: ("discovery", hash_key_part(f"tei={tei}&purl={purl}")))
def discovery(
    request: HttpRequest,
    tei: str | None = Query(None, max_length=2048, description="Transparency Exchange Identifier (TEI)"),  # type: ignore[type-arg]
    purl: str | None = Query(None, max_length=2048, description="Package URL of the product"),  # type: ignore[type-arg]
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    team = getattr(request, TEA_TEAM_ATTR)
    if (tei is None) == (purl is None):
        return _invalid("Give exactly one of tei and purl")

    try:
        releases = tea_tei_mapper(team, tei) if tei is not None else tea_purl_mapper(team, purl or "")
    except TEIParseError:
        log.warning(
            "Discovery: invalid identifier (tei=%s, purl=%s)",
            _sanitize_for_log(tei or ""),
            _sanitize_for_log(purl or ""),
        )
        return _invalid("Invalid TEI" if tei is not None else "Invalid PURL")

    if not releases:
        return NOT_FOUND
    return 200, _discovery_results(request, team, workspace_key, releases)


# =============================================================================
# Products and product releases
# =============================================================================


@router.get(
    "/products",
    response={200: TEAPaginatedProductResponse, 400: TEAErrorResponse},
    summary="Query TEA Products",
    description="Returns TEA products, optionally filtered by identifier.",
)
@_cached(_page_key("products"))
def query_products(
    request: HttpRequest,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
    idType: IdType | None = Query(None, description="Type of identifier to filter by"),  # type: ignore[type-arg]
    idValue: str | None = Query(None, max_length=2048, description="Identifier value to filter by"),  # type: ignore[type-arg]
    pageSize: int = Query(25, ge=1, le=100, description="The maximum number of results to return"),  # type: ignore[type-arg]
    pageToken: str | None = Query(None, max_length=2048, description="nextPageToken of the previous page"),  # type: ignore[type-arg]
    sortField: Literal["name"] = Query("name", description="The field to sort by"),  # type: ignore[type-arg]
    sortOrder: SortOrder = Query("asc", description="The direction of the sort"),  # type: ignore[type-arg]
) -> Any:
    team = getattr(request, TEA_TEAM_ATTR)
    products = Product.objects.filter(team=team, is_public=True).prefetch_related("identifiers")
    if idType and idValue:
        products = _apply_identifier_filter(products, team, idType, idValue)
    return _page(
        request,
        TEAPaginatedProductResponse,
        _ordered(products, ["name"], sortOrder),
        lambda rows: [_build_product_response(p) for p in rows],
        page_size=pageSize,
        page_token=pageToken,
        state=[idType, idValue, sortField, sortOrder],
    )


@router.get(
    "/product/{uuid}",
    response={200: TEAProduct, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get a TEA Product",
)
@_cached(lambda uuid, **_: ("product", uuid))
def get_product(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    team = getattr(request, TEA_TEAM_ATTR)
    product = _queryset_get_or_404(
        Product.objects.prefetch_related("identifiers"), uuid=uuid, team=team, is_public=True
    )
    if isinstance(product, tuple):
        return product
    return 200, _build_product_response(product)


@router.get(
    "/product/{uuid}/releases",
    response={200: TEAPaginatedProductReleaseResponse, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="List the releases of a TEA Product",
    description="A version sorts as a string, in the database's collation.",
)
@_cached(_page_key("product_releases"))
def list_product_releases(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
    pageSize: int = Query(25, ge=1, le=100, description="The maximum number of results to return"),  # type: ignore[type-arg]
    pageToken: str | None = Query(None, max_length=2048, description="nextPageToken of the previous page"),  # type: ignore[type-arg]
    sortField: ReleaseSortField = Query("createdDate", description="The field to sort by"),  # type: ignore[type-arg]
    sortOrder: SortOrder = Query("asc", description="The direction of the sort"),  # type: ignore[type-arg]
) -> Any:
    team = getattr(request, TEA_TEAM_ATTR)
    product = _get_or_404(Product, uuid=uuid, team=team, is_public=True)
    if isinstance(product, tuple):
        return product
    return _page(
        request,
        TEAPaginatedProductReleaseResponse,
        _ordered(_public_releases(product), [_RELEASE_SORT[sortField]], sortOrder),
        _release_rows,
        page_size=pageSize,
        page_token=pageToken,
        state=[sortField, sortOrder],
    )


@router.get(
    "/productReleases",
    response={200: TEAPaginatedProductReleaseResponse, 400: TEAErrorResponse},
    summary="Query TEA Product Releases",
    description="Returns TEA product releases, optionally filtered by identifier. "
    "A version sorts as a string, in the database's collation.",
)
@_cached(_page_key("product_releases_query"))
def query_product_releases(
    request: HttpRequest,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
    idType: IdType | None = Query(None, description="Type of identifier to filter by"),  # type: ignore[type-arg]
    idValue: str | None = Query(None, max_length=2048, description="Identifier value to filter by"),  # type: ignore[type-arg]
    pageSize: int = Query(25, ge=1, le=100, description="The maximum number of results to return"),  # type: ignore[type-arg]
    pageToken: str | None = Query(None, max_length=2048, description="nextPageToken of the previous page"),  # type: ignore[type-arg]
    sortField: ReleaseSortField = Query("createdDate", description="The field to sort by"),  # type: ignore[type-arg]
    sortOrder: SortOrder = Query("asc", description="The direction of the sort"),  # type: ignore[type-arg]
) -> Any:
    team = getattr(request, TEA_TEAM_ATTR)
    products_with_versioned = (
        Release.objects.filter(product__team=team, product__is_public=True, is_latest=False)
        .values_list("product_id", flat=True)
        .distinct()
    )
    releases = Release.objects.filter(product__team=team, product__is_public=True).exclude(
        is_latest=True, product_id__in=products_with_versioned
    )
    if idType and idValue:
        releases = _apply_identifier_filter(releases, team, idType, idValue, filter_releases=True)
    return _page(
        request,
        TEAPaginatedProductReleaseResponse,
        _ordered(releases, [_RELEASE_SORT[sortField]], sortOrder),
        _release_rows,
        page_size=pageSize,
        page_token=pageToken,
        state=[idType, idValue, sortField, sortOrder],
    )


def _get_public_release(team: Any, uuid: str) -> Release | tuple[int, TEAErrorResponse]:
    return _get_or_404(Release, uuid=uuid, product__team=team, product__is_public=True)


@router.get(
    "/productRelease/{uuid}",
    response={200: TEAProductReleaseWithCollection, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get a TEA Product Release with its latest collection",
)
@_cached(lambda uuid, **_: ("product_release", uuid))
def get_product_release(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
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
    collection = _build_collection_response(release, BELONGS_TO_PRODUCT_RELEASE, _get_base_url(request))
    return 200, TEAProductReleaseWithCollection.model_validate(
        {**_build_product_release_response(release).model_dump(), "latest_collection": collection}
    )


@router.get(
    "/productRelease/{uuid}/collections",
    response={200: TEAPaginatedCollectionResponse, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="List the collections of a TEA Product Release",
    description="sbomify keeps only the latest collection version, so the list holds that one.",
)
@_cached(_page_key("product_release_collections"))
def list_product_release_collections(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
    pageSize: int = Query(25, ge=1, le=100, description="The maximum number of results to return"),  # type: ignore[type-arg]
    pageToken: str | None = Query(None, max_length=2048, description="nextPageToken of the previous page"),  # type: ignore[type-arg]
    sortField: Literal["version"] = Query("version", description="The field to sort by"),  # type: ignore[type-arg]
    sortOrder: SortOrder = Query("asc", description="The direction of the sort"),  # type: ignore[type-arg]
) -> Any:
    release = _get_public_release(getattr(request, TEA_TEAM_ATTR), uuid)
    if isinstance(release, tuple):
        return release
    collection = _build_collection_response(release, BELONGS_TO_PRODUCT_RELEASE, _get_base_url(request))
    return _page(
        request,
        TEAPaginatedCollectionResponse,
        [collection],
        list,
        page_size=pageSize,
        page_token=pageToken,
        state=[sortField, sortOrder],
    )


@router.get(
    "/productRelease/{uuid}/collection/latest",
    response={200: TEACollection, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get the latest collection of a TEA Product Release",
)
@_cached(lambda uuid, **_: ("product_release", uuid, "collection", "latest"))
def get_latest_product_release_collection(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    release = _get_public_release(getattr(request, TEA_TEAM_ATTR), uuid)
    if isinstance(release, tuple):
        return release
    return 200, _build_collection_response(release, BELONGS_TO_PRODUCT_RELEASE, _get_base_url(request))


@router.get(
    "/productRelease/{uuid}/collection/{int:collectionVersion}",
    response={200: TEACollection, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get one collection version of a TEA Product Release",
    description="sbomify keeps only the latest collection version; an earlier one is not found.",
)
@_cached(lambda uuid, collectionVersion, **_: ("product_release", uuid, "collection", str(collectionVersion)))
def get_product_release_collection_by_version(
    request: HttpRequest,
    uuid: str,
    collectionVersion: int,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    release = _get_public_release(getattr(request, TEA_TEAM_ATTR), uuid)
    if isinstance(release, tuple):
        return release
    if collectionVersion != release.collection_version:
        return NOT_FOUND
    return 200, _build_collection_response(release, BELONGS_TO_PRODUCT_RELEASE, _get_base_url(request))


# =============================================================================
# Components and component releases
# =============================================================================


@router.get(
    "/components",
    response={200: TEAPaginatedComponentResponse, 400: TEAErrorResponse},
    summary="Query TEA Components",
    description="Returns public TEA components. sbomify publishes no component identifiers, "
    "so an identifier filter matches none.",
)
@_cached(_page_key("components"))
def query_components(
    request: HttpRequest,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
    idType: IdType | None = Query(None, description="Type of identifier to filter by"),  # type: ignore[type-arg]
    idValue: str | None = Query(None, max_length=2048, description="Identifier value to filter by"),  # type: ignore[type-arg]
    pageSize: int = Query(25, ge=1, le=100, description="The maximum number of results to return"),  # type: ignore[type-arg]
    pageToken: str | None = Query(None, max_length=2048, description="nextPageToken of the previous page"),  # type: ignore[type-arg]
    sortField: Literal["name"] = Query("name", description="The field to sort by"),  # type: ignore[type-arg]
    sortOrder: SortOrder = Query("asc", description="The direction of the sort"),  # type: ignore[type-arg]
) -> Any:
    team = getattr(request, TEA_TEAM_ATTR)
    components = Component.objects.filter(team=team, visibility=Component.Visibility.PUBLIC)
    if idType and idValue:
        components = components.none()
    return _page(
        request,
        TEAPaginatedComponentResponse,
        _ordered(components, ["name"], sortOrder),
        lambda rows: [_build_component_response(c) for c in rows],
        page_size=pageSize,
        page_token=pageToken,
        state=[idType, idValue, sortField, sortOrder],
    )


@router.get(
    "/component/{uuid}",
    response={200: TEAComponent, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get a TEA Component",
)
@_cached(lambda uuid, **_: ("component", uuid))
def get_component(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    team = getattr(request, TEA_TEAM_ATTR)
    component = _get_or_404(Component, uuid=uuid, team=team, visibility=Component.Visibility.PUBLIC)
    if isinstance(component, tuple):
        return component
    return 200, _build_component_response(component)


@router.get(
    "/component/{uuid}/releases",
    response={200: TEAPaginatedComponentReleaseResponse, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="List the releases of a TEA Component",
    description="A version sorts as a string, in the database's collation. A component release records "
    "no separate release date, so releaseDate sorts as createdDate.",
)
@_cached(_page_key("component_releases"))
def list_component_releases(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
    pageSize: int = Query(25, ge=1, le=100, description="The maximum number of results to return"),  # type: ignore[type-arg]
    pageToken: str | None = Query(None, max_length=2048, description="nextPageToken of the previous page"),  # type: ignore[type-arg]
    sortField: ReleaseSortField = Query("createdDate", description="The field to sort by"),  # type: ignore[type-arg]
    sortOrder: SortOrder = Query("asc", description="The direction of the sort"),  # type: ignore[type-arg]
) -> Any:
    team = getattr(request, TEA_TEAM_ATTR)
    component = _get_or_404(Component, uuid=uuid, team=team, visibility=Component.Visibility.PUBLIC)
    if isinstance(component, tuple):
        return component
    releases = ComponentRelease.objects.filter(component=component).select_related("component")
    return _page(
        request,
        TEAPaginatedComponentReleaseResponse,
        _ordered(releases, [_COMPONENT_RELEASE_SORT[sortField]], sortOrder),
        lambda rows: [_build_component_release_response(cr) for cr in rows],
        page_size=pageSize,
        page_token=pageToken,
        state=[sortField, sortOrder],
    )


@router.get(
    "/componentReleases",
    response={200: TEAPaginatedComponentReleaseResponse, 400: TEAErrorResponse},
    summary="Query TEA Component Releases",
    description="Returns the releases of public TEA components. sbomify publishes no component release "
    "identifiers, so an identifier filter matches none.",
)
@_cached(_page_key("component_releases_query"))
def query_component_releases(
    request: HttpRequest,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
    idType: IdType | None = Query(None, description="Type of identifier to filter by"),  # type: ignore[type-arg]
    idValue: str | None = Query(None, max_length=2048, description="Identifier value to filter by"),  # type: ignore[type-arg]
    pageSize: int = Query(25, ge=1, le=100, description="The maximum number of results to return"),  # type: ignore[type-arg]
    pageToken: str | None = Query(None, max_length=2048, description="nextPageToken of the previous page"),  # type: ignore[type-arg]
    sortField: ReleaseSortField = Query("createdDate", description="The field to sort by"),  # type: ignore[type-arg]
    sortOrder: SortOrder = Query("asc", description="The direction of the sort"),  # type: ignore[type-arg]
) -> Any:
    team = getattr(request, TEA_TEAM_ATTR)
    releases = ComponentRelease.objects.filter(
        component__team=team, component__visibility=Component.Visibility.PUBLIC
    ).select_related("component")
    if idType and idValue:
        releases = releases.none()
    return _page(
        request,
        TEAPaginatedComponentReleaseResponse,
        _ordered(releases, [_COMPONENT_RELEASE_SORT[sortField]], sortOrder),
        lambda rows: [_build_component_release_response(cr) for cr in rows],
        page_size=pageSize,
        page_token=pageToken,
        state=[idType, idValue, sortField, sortOrder],
    )


def _get_public_component_release(team: Any, uuid: str) -> ComponentRelease | tuple[int, TEAErrorResponse]:
    return _queryset_get_or_404(
        ComponentRelease.objects.select_related("component"),
        uuid=uuid,
        component__team=team,
        component__visibility=Component.Visibility.PUBLIC,
    )


@router.get(
    "/componentRelease/{uuid}",
    response={200: TEAComponentReleaseWithCollection, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get a TEA Component Release with its latest collection",
)
@_cached(lambda uuid, **_: ("component_release", uuid))
def get_component_release(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    component_release = _get_public_component_release(getattr(request, TEA_TEAM_ATTR), uuid)
    if isinstance(component_release, tuple):
        return component_release
    collection = _build_component_release_collection_response(
        component_release, BELONGS_TO_COMPONENT_RELEASE, _get_base_url(request)
    )
    return 200, TEAComponentReleaseWithCollection.model_validate(
        {**_build_component_release_response(component_release).model_dump(), "latest_collection": collection}
    )


@router.get(
    "/componentRelease/{uuid}/collections",
    response={200: TEAPaginatedCollectionResponse, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="List the collections of a TEA Component Release",
    description="sbomify keeps only the latest collection version, so the list holds that one.",
)
@_cached(_page_key("component_release_collections"))
def list_component_release_collections(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
    pageSize: int = Query(25, ge=1, le=100, description="The maximum number of results to return"),  # type: ignore[type-arg]
    pageToken: str | None = Query(None, max_length=2048, description="nextPageToken of the previous page"),  # type: ignore[type-arg]
    sortField: Literal["version"] = Query("version", description="The field to sort by"),  # type: ignore[type-arg]
    sortOrder: SortOrder = Query("asc", description="The direction of the sort"),  # type: ignore[type-arg]
) -> Any:
    component_release = _get_public_component_release(getattr(request, TEA_TEAM_ATTR), uuid)
    if isinstance(component_release, tuple):
        return component_release
    collection = _build_component_release_collection_response(
        component_release, BELONGS_TO_COMPONENT_RELEASE, _get_base_url(request)
    )
    return _page(
        request,
        TEAPaginatedCollectionResponse,
        [collection],
        list,
        page_size=pageSize,
        page_token=pageToken,
        state=[sortField, sortOrder],
    )


@router.get(
    "/componentRelease/{uuid}/collection/latest",
    response={200: TEACollection, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get the latest collection of a TEA Component Release",
)
@_cached(lambda uuid, **_: ("component_release", uuid, "collection", "latest"))
def get_latest_component_release_collection(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    component_release = _get_public_component_release(getattr(request, TEA_TEAM_ATTR), uuid)
    if isinstance(component_release, tuple):
        return component_release
    return 200, _build_component_release_collection_response(
        component_release, BELONGS_TO_COMPONENT_RELEASE, _get_base_url(request)
    )


@router.get(
    "/componentRelease/{uuid}/collection/{int:collectionVersion}",
    response={200: TEACollection, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get one collection version of a TEA Component Release",
    description="sbomify keeps only the latest collection version; an earlier one is not found.",
)
@_cached(lambda uuid, collectionVersion, **_: ("component_release", uuid, "collection", str(collectionVersion)))
def get_component_release_collection_by_version(
    request: HttpRequest,
    uuid: str,
    collectionVersion: int,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    component_release = _get_public_component_release(getattr(request, TEA_TEAM_ATTR), uuid)
    if isinstance(component_release, tuple):
        return component_release
    if collectionVersion != component_release.collection_version:
        return NOT_FOUND
    return 200, _build_component_release_collection_response(
        component_release, BELONGS_TO_COMPONENT_RELEASE, _get_base_url(request)
    )


# =============================================================================
# CLE (ECMA-428 Common Lifecycle Enumeration)
# =============================================================================


@router.get(
    "/product/{uuid}/cle",
    response={200: TEACLE, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get the lifecycle events of a TEA Product",
)
@_cached(lambda uuid, **_: ("product", uuid, "cle"))
def get_product_cle(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    product = _get_or_404(Product, uuid=uuid, team=getattr(request, TEA_TEAM_ATTR), is_public=True)
    if isinstance(product, tuple):
        return product
    return _cle(get_cle_document(product), uuid)


@router.get(
    "/productRelease/{uuid}/cle",
    response={200: TEACLE, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get the lifecycle events of a TEA Product Release",
)
@_cached(lambda uuid, **_: ("product_release", uuid, "cle"))
def get_product_release_cle(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    release = _get_public_release(getattr(request, TEA_TEAM_ATTR), uuid)
    if isinstance(release, tuple):
        return release
    return _cle(get_release_cle_document(release), uuid)


@router.get(
    "/component/{uuid}/cle",
    response={200: TEACLE, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get the lifecycle events of a TEA Component",
)
@_cached(lambda uuid, **_: ("component", uuid, "cle"))
def get_component_cle(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    team = getattr(request, TEA_TEAM_ATTR)
    component = _get_or_404(Component, uuid=uuid, team=team, visibility=Component.Visibility.PUBLIC)
    if isinstance(component, tuple):
        return component
    return _cle(get_component_cle_document(component), uuid)


@router.get(
    "/componentRelease/{uuid}/cle",
    response={200: TEACLE, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get the lifecycle events of a TEA Component Release",
)
@_cached(lambda uuid, **_: ("component_release", uuid, "cle"))
def get_component_release_cle(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    component_release = _get_public_component_release(getattr(request, TEA_TEAM_ATTR), uuid)
    if isinstance(component_release, tuple):
        return component_release
    return _cle(get_component_release_cle_document(component_release), uuid)


# =============================================================================
# Artifacts
# =============================================================================
#
# sbomify never changes an uploaded artifact, so every artifact has exactly one
# revision, version 1, and "latest" is that revision.


def _artifact_revision(request: HttpRequest, uuid: str, version: int | None) -> TEAArtifact | tuple[int, Any]:
    found = _find_artifact(getattr(request, TEA_TEAM_ATTR), uuid)
    if found is None or version not in (None, 1):
        return NOT_FOUND
    return _build_artifact(found, _get_base_url(request))


@router.get(
    "/artifact/{uuid}/latest",
    response={200: TEAArtifact, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get the metadata of the latest TEA Artifact revision",
)
@_cached(lambda uuid, **_: ("artifact", uuid, "latest"))
def get_latest_artifact(
    request: HttpRequest,
    uuid: str,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    artifact = _artifact_revision(request, uuid, None)
    return artifact if isinstance(artifact, tuple) else (200, artifact)


@router.get(
    "/artifact/{uuid}/{int:artifactVersion}",
    response={200: TEAArtifact, 400: TEAErrorResponse, 404: TEAErrorResponse},
    summary="Get the metadata of one TEA Artifact revision",
)
@_cached(lambda uuid, artifactVersion, **_: ("artifact", uuid, str(artifactVersion)))
def get_artifact_by_version(
    request: HttpRequest,
    uuid: str,
    artifactVersion: int,
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    artifact = _artifact_revision(request, uuid, artifactVersion)
    return artifact if isinstance(artifact, tuple) else (200, artifact)


def _media_type(value: str) -> tuple[str, list[str]]:
    """A media type as TEA compares it: type and subtype ignore case, parameters must match exactly."""
    base, *params = value.split(";")
    return base.strip().lower(), sorted(param.strip() for param in params if param.strip())


def _download(
    request: HttpRequest, uuid: str, version: int | None, media_type: str | None, *, signature: bool
) -> HttpResponse | tuple[int, Any]:
    """Redirect to the content, or the signature, of an artifact revision's one format.

    The format's url is not published when it has no checksum, so this endpoint is
    where a TEA 1.0.0 client finds that content.
    """
    found = _find_artifact(getattr(request, TEA_TEAM_ATTR), uuid)
    if found is None or version not in (None, 1):
        return NOT_FOUND
    base_url = _get_base_url(request)
    fmt = _sbom_format(found, base_url) if isinstance(found, SBOM) else _document_format(found, base_url)
    if media_type is not None and _media_type(media_type) != _media_type(fmt["media_type"]):
        return 406, TEAErrorResponse(error=ErrorType.NO_ACCEPTABLE_FORMAT)
    location = fmt["signature_url"] if signature else fmt["url"]
    if not location:
        return 404, TEAErrorResponse(error=ErrorType.SIGNATURE_NOT_FOUND)
    return HttpResponseRedirect(location)


_DOWNLOAD_RESPONSES: dict[int, Any] = {302: None, 400: TEAErrorResponse, 404: TEAErrorResponse, 406: TEAErrorResponse}


@router.get(
    "/artifact/{uuid}/latest/download",
    response=_DOWNLOAD_RESPONSES,
    summary="Download the content of the latest TEA Artifact revision",
)
@_cached(lambda uuid, **_: ("artifact", uuid, "latest", "download"))
def download_latest_artifact(
    request: HttpRequest,
    uuid: str,
    mediaType: str | None = Query(None, max_length=255, description="The mediaType of the format to download"),  # type: ignore[type-arg]
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    return _download(request, uuid, None, mediaType, signature=False)


@router.get(
    "/artifact/{uuid}/{int:artifactVersion}/download",
    response=_DOWNLOAD_RESPONSES,
    summary="Download the content of one TEA Artifact revision",
)
@_cached(lambda uuid, artifactVersion, **_: ("artifact", uuid, str(artifactVersion), "download"))
def download_artifact_by_version(
    request: HttpRequest,
    uuid: str,
    artifactVersion: int,
    mediaType: str | None = Query(None, max_length=255, description="The mediaType of the format to download"),  # type: ignore[type-arg]
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    return _download(request, uuid, artifactVersion, mediaType, signature=False)


@router.get(
    "/artifact/{uuid}/latest/signature/download",
    response=_DOWNLOAD_RESPONSES,
    summary="Download the signature of the latest TEA Artifact revision",
)
@_cached(lambda uuid, **_: ("artifact", uuid, "latest", "signature"))
def download_latest_artifact_signature(
    request: HttpRequest,
    uuid: str,
    mediaType: str | None = Query(None, max_length=255, description="The mediaType of the format to download"),  # type: ignore[type-arg]
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    return _download(request, uuid, None, mediaType, signature=True)


@router.get(
    "/artifact/{uuid}/{int:artifactVersion}/signature/download",
    response=_DOWNLOAD_RESPONSES,
    summary="Download the signature of one TEA Artifact revision",
)
@_cached(lambda uuid, artifactVersion, **_: ("artifact", uuid, str(artifactVersion), "signature"))
def download_artifact_signature_by_version(
    request: HttpRequest,
    uuid: str,
    artifactVersion: int,
    mediaType: str | None = Query(None, max_length=255, description="The mediaType of the format to download"),  # type: ignore[type-arg]
    workspace_key: str | None = Query(None, max_length=255, description="Workspace key"),  # type: ignore[type-arg]
) -> Any:
    return _download(request, uuid, artifactVersion, mediaType, signature=True)
