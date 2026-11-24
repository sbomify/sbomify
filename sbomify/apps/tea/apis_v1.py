"""
TEA (Transparency Exchange API) 1.0.0 endpoints, served at ``/tea/v1.0.0/``.

The 0.4.0 endpoints in ``apis.py`` stay where they are, and both versions share
its lookups and builders. 1.0.0 differs in pagination (opaque page tokens and a
sort order), its error body, the latest collection inside a product release,
artifact revisions, discovery by PURL, and the download endpoints.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import wraps
from typing import TYPE_CHECKING, Any, Literal

from django.core import signing
from django.db.models import F, OrderBy, Prefetch, QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from libtea.models import ErrorType
from ninja import Query, Router

from sbomify.apps.core.models import Component, ComponentRelease, Product, Release, ReleaseArtifact
from sbomify.apps.core.services.cle import (
    get_cle_document,
    get_component_cle_document,
    get_component_release_cle_document,
    get_release_cle_document,
)
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.tea.apis import (
    BELONGS_TO_COMPONENT_RELEASE,
    BELONGS_TO_PRODUCT_RELEASE,
    _apply_identifier_filter,
    _build_artifact,
    _build_collection_response,
    _build_component_release_collection_response,
    _build_component_release_response,
    _build_component_response,
    _build_product_release_response,
    _build_product_response,
    _discovery_results,
    _find_artifact,
    _get_base_url,
    _get_or_404,
    _prefetch_releases,
    _queryset_get_or_404,
)
from sbomify.apps.tea.cache import TEA_TEAM_ATTR, hash_key_part, tea_cached
from sbomify.apps.tea.mappers import TEA_V1_VERSION, TEIParseError, tea_purl_mapper, tea_tei_mapper
from sbomify.apps.tea.schemas import (
    TEACLE,
    TEAArtifact,
    TEABadRequestResponse,
    TEACollectionV1,
    TEAComponent,
    TEAComponentReleaseWithCollectionV1,
    TEADiscoveryInfo,
    TEAErrorResponse,
    TEAPaginatedCollectionResponse,
    TEAPaginatedComponentReleaseResponse,
    TEAPaginatedComponentResponse,
    TEAPaginatedProductReleaseResponse,
    TEAPaginatedProductResponse,
    TEAProduct,
    TEAProductReleaseWithCollection,
)
from sbomify.apps.tea.utils import _sanitize_for_log
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from libtea.models import CLE

log = getLogger(__name__)

# TEA 1.0.0 responses carry no null and no empty default the server did not set.
router = Router(tags=["TEA"], auth=None, by_alias=True, exclude_none=True, exclude_unset=True)

NOT_FOUND = (404, TEAErrorResponse(error=ErrorType.OBJECT_UNKNOWN))
_PAGE_SALT = "sbomify.tea.v1.page-token"

IdType = Literal["CPE", "TEI", "PURL", "COMPLIANCE_DOCUMENT"]
SortOrder = Literal["asc", "desc"]
ReleaseSortField = Literal["createdDate", "releaseDate", "version"]


def _invalid(message: str, error: ErrorType = ErrorType.INVALID_REQUEST) -> tuple[int, TEAErrorResponse]:
    return 400, TEAErrorResponse(error=error, message=message)


def _cached(key_builder: Callable[..., tuple[str, ...]]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """``tea_cached`` for 1.0.0: keys apart from 0.4.0's, and its 400 body in the 1.0.0 shape."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        cached = tea_cached(lambda **kwargs: (TEA_V1_VERSION, *key_builder(**kwargs)))(func)

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
    return [_build_product_release_response(r, v1=True) for r in _prefetch_releases([r.id for r in releases])]


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
        lambda rows: [_build_product_response(p, v1=True) for p in rows],
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
    return 200, _build_product_response(product, v1=True)


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
    collection = _build_collection_response(release, BELONGS_TO_PRODUCT_RELEASE, _get_base_url(request), v1=True)
    return 200, TEAProductReleaseWithCollection.model_validate(
        {**_build_product_release_response(release, v1=True).model_dump(), "latest_collection": collection}
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
    collection = _build_collection_response(release, BELONGS_TO_PRODUCT_RELEASE, _get_base_url(request), v1=True)
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
    response={200: TEACollectionV1, 400: TEAErrorResponse, 404: TEAErrorResponse},
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
    return 200, _build_collection_response(release, BELONGS_TO_PRODUCT_RELEASE, _get_base_url(request), v1=True)


@router.get(
    "/productRelease/{uuid}/collection/{int:collectionVersion}",
    response={200: TEACollectionV1, 400: TEAErrorResponse, 404: TEAErrorResponse},
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
    return 200, _build_collection_response(release, BELONGS_TO_PRODUCT_RELEASE, _get_base_url(request), v1=True)


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
    response={200: TEAComponentReleaseWithCollectionV1, 400: TEAErrorResponse, 404: TEAErrorResponse},
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
        component_release, BELONGS_TO_COMPONENT_RELEASE, _get_base_url(request), v1=True
    )
    return 200, TEAComponentReleaseWithCollectionV1.model_validate(
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
        component_release, BELONGS_TO_COMPONENT_RELEASE, _get_base_url(request), v1=True
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
    response={200: TEACollectionV1, 400: TEAErrorResponse, 404: TEAErrorResponse},
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
        component_release, BELONGS_TO_COMPONENT_RELEASE, _get_base_url(request), v1=True
    )


@router.get(
    "/componentRelease/{uuid}/collection/{int:collectionVersion}",
    response={200: TEACollectionV1, 400: TEAErrorResponse, 404: TEAErrorResponse},
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
        component_release, BELONGS_TO_COMPONENT_RELEASE, _get_base_url(request), v1=True
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
    return _build_artifact(found, _get_base_url(request), v1=True)


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
    # The 0.4.0 shape always carries the format's url.
    fmt = _build_artifact(found, _get_base_url(request)).formats[0]
    if media_type is not None and _media_type(media_type) != _media_type(fmt.media_type or ""):
        return 406, TEAErrorResponse(error=ErrorType.NO_ACCEPTABLE_FORMAT)
    location = fmt.signature_url if signature else fmt.url
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
