"""TEA subscriptions: find a component on another TEA 1.0 server, subscribe to it, and pin its artifacts.

Browsing reads the remote server on the caller's behalf, so it needs the right
to create components here, as subscribing does.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.http import HttpRequest
from ninja import Query, Router
from ninja.security import django_auth
from ninja.throttling import BaseThrottle
from pydantic import BaseModel, Field

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from sbomify.apps.access_tokens.throttling import AccessTokenHeavyRateThrottle, AccessTokenRateThrottle
from sbomify.apps.core.apis import _get_user_team_id, _is_guest_member, schedule_broadcast
from sbomify.apps.core.authz import can
from sbomify.apps.core.domain.exceptions import DomainError
from sbomify.apps.core.models import Release
from sbomify.apps.core.schemas import ErrorCode, ErrorResponse
from sbomify.apps.tea import pins
from sbomify.apps.tea.models import TeaRemoteArtifact, TeaSubscription
from sbomify.apps.tea.services import remote
from sbomify.apps.tea.services.subscriptions import Subscribe, authorize_targets, describe, subscribe
from sbomify.apps.tea.tasks import check_tea_subscription
from sbomify.apps.teams.models import Workspace

router = Router(tags=["TEA subscriptions"], auth=(PersonalAccessTokenAuth(), django_auth))
# A per-operation throttle replaces the global one, so it is listed again.
OUTBOUND: list[BaseThrottle] = [AccessTokenRateThrottle(), AccessTokenHeavyRateThrottle()]
ERRORS: dict[int, Any] = {
    400: ErrorResponse,
    403: ErrorResponse,
    404: ErrorResponse,
    409: ErrorResponse,
    502: ErrorResponse,
}
_ERROR_CODES = {
    400: ErrorCode.INVALID_DATA,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.BAD_REQUEST,
}


class ServerOut(BaseModel):
    base_url: str
    spec_version: str


class ConnectIn(BaseModel):
    server: str = Field(..., max_length=500, description="A domain, or a TEA API base ending in its version")


class PageOut(BaseModel):
    items: list[dict[str, Any]]
    next_page_token: str | None = None


class SubscribeIn(BaseModel):
    server: str = Field(..., max_length=500)
    component_uuid: str = Field(..., max_length=64)
    release_uuids: list[str] = Field(default_factory=list, description="Remote releases to always watch")
    tei: str = Field("", max_length=2048)
    name: str = Field("", max_length=255, description="Defaults to the remote component's name")
    product_ids: list[str] = Field(default_factory=list)
    pin_release_ids: list[str] = Field(default_factory=list, description="Product releases to pin into now")


class EventOut(BaseModel):
    kind: str
    title: str
    detail: dict[str, Any]
    created_at: datetime


class PinIn(BaseModel):
    remote_artifact_id: str
    allow_replacement: bool = False


class PinOut(BaseModel):
    id: str
    release_id: str
    remote_artifact_id: str
    uuid: str
    version: int
    name: str
    state: str
    auto_pinned: bool
    findings: list[str]


def _fail(error: DomainError) -> tuple[int, dict[str, Any]]:
    return error.status_code, {"detail": error.detail, "error_code": _ERROR_CODES.get(error.status_code)}


def _workspace(request: HttpRequest) -> Workspace | tuple[int, dict[str, Any]]:
    if _is_guest_member(request):
        return 403, {"detail": "Guest members can only access public pages", "error_code": ErrorCode.FORBIDDEN}
    team_id = _get_user_team_id(request)
    team = Workspace.objects.filter(pk=team_id).first() if team_id else None
    if team is None:
        return 403, {"detail": "No current team selected", "error_code": ErrorCode.NO_CURRENT_TEAM}
    if not can(request, "component:create", team):
        return 403, {"detail": "You can't subscribe to components in this workspace", "error_code": ErrorCode.FORBIDDEN}
    return team


def _subscription(request: HttpRequest, component_id: str, action: str) -> TeaSubscription | tuple[int, Any]:
    subscription = (
        TeaSubscription.objects.select_related("component", "latest_release").filter(component_id=component_id).first()
    )
    if subscription is None or not can(request, "component:read_internal", subscription.component):
        return 404, {"detail": "Subscription not found", "error_code": ErrorCode.NOT_FOUND}
    if not can(request, action, subscription.component):
        return 403, {"detail": "You can't do that to this subscription", "error_code": ErrorCode.FORBIDDEN}
    return subscription


def _release(request: HttpRequest, release_id: str, action: str) -> Release | tuple[int, Any]:
    release = Release.objects.select_related("product__team").filter(pk=release_id).first()
    if release is None or not can(request, "release:read", release.product):
        return 404, {"detail": "Release not found", "error_code": ErrorCode.RELEASE_NOT_FOUND}
    if not can(request, action, release.product):
        return 403, {"detail": "You can't change this release", "error_code": ErrorCode.FORBIDDEN}
    return release


def _pin_out(pin: Any) -> PinOut:
    artifact = pin.remote_artifact
    return PinOut(
        id=pin.id,
        release_id=pin.release_id,
        remote_artifact_id=artifact.id,
        uuid=artifact.uuid,
        version=artifact.version,
        name=artifact.name,
        state=artifact.state,
        auto_pinned=pin.auto_pinned,
        findings=[key for key, _ in pins.findings(artifact)],
    )


# --- Finding a component on a remote server -------------------------------------------------


@router.post("/connect", response={200: ServerOut, **ERRORS}, throttle=OUTBOUND)
def connect(request: HttpRequest, payload: ConnectIn) -> Any:
    """Resolve a domain or a versioned API base to the server's TEA 1.0 API. A 0.4.0-only server is refused."""
    team = _workspace(request)
    if isinstance(team, tuple):
        return team
    try:
        server = remote.connect(payload.server)
    except DomainError as error:
        return _fail(error)
    return 200, ServerOut(base_url=server.base_url, spec_version=server.spec_version)


def _browse(request: HttpRequest, server: str, read: Any) -> Any:
    team = _workspace(request)
    if isinstance(team, tuple):
        return team
    try:
        return 200, read(remote.connect(server))
    except DomainError as error:
        return _fail(error)


@router.get("/browse/products", response={200: PageOut, **ERRORS}, throttle=OUTBOUND)
def browse_products(
    request: HttpRequest,
    server: str = Query(..., max_length=500),  # type: ignore[type-arg]
    id_type: str | None = Query(None, pattern="^(PURL|CPE|TEI)$"),  # type: ignore[type-arg]
    id_value: str | None = Query(None, max_length=2048),  # type: ignore[type-arg]
    page_token: str | None = Query(None, max_length=2048),  # type: ignore[type-arg]
) -> Any:
    """Search a server's products by identifier, or list them."""
    return _browse(
        request,
        server,
        lambda s: remote.list_products(s, id_type=id_type, id_value=id_value, page_token=page_token).__dict__,
    )


@router.get("/browse/products/{product_uuid}/releases", response={200: PageOut, **ERRORS}, throttle=OUTBOUND)
def browse_product_releases(
    request: HttpRequest,
    product_uuid: str,
    server: str = Query(..., max_length=500),  # type: ignore[type-arg]
    page_token: str | None = Query(None, max_length=2048),  # type: ignore[type-arg]
) -> Any:
    return _browse(request, server, lambda s: remote.product_releases(s, product_uuid, page_token=page_token).__dict__)


@router.get(
    "/browse/product-releases/{product_release_uuid}/components", response={200: dict, **ERRORS}, throttle=OUTBOUND
)
def browse_product_release_components(
    request: HttpRequest,
    product_release_uuid: str,
    server: str = Query(..., max_length=500),  # type: ignore[type-arg]
) -> Any:
    """A product release's components, each with its component release and that release's latest artifacts."""
    return _browse(request, server, lambda s: remote.product_release_components(s, product_release_uuid))


@router.get(
    "/browse/components/{component_uuid}/releases", response={200: list[dict[str, Any]], **ERRORS}, throttle=OUTBOUND
)
def browse_component_releases(
    request: HttpRequest,
    component_uuid: str,
    server: str = Query(..., max_length=500),  # type: ignore[type-arg]
) -> Any:
    return _browse(request, server, lambda s: remote.component_releases(s, component_uuid))


@router.get("/browse/tei", response={200: dict, **ERRORS}, throttle=OUTBOUND)
def browse_tei(request: HttpRequest, tei: str = Query(..., max_length=2048)) -> Any:  # type: ignore[type-arg]
    """Resolve a TEI through its own domain to that server and the product releases it names."""
    team = _workspace(request)
    if isinstance(team, tuple):
        return team
    try:
        match = remote.resolve_tei(tei)
    except DomainError as error:
        return _fail(error)
    return 200, {"server": match.server.base_url, "product_release_uuids": match.product_release_uuids}


# --- Subscriptions --------------------------------------------------------------------------


@router.post("/", response={201: dict, **ERRORS}, throttle=OUTBOUND)
def create_subscription(request: HttpRequest, payload: SubscribeIn) -> Any:
    """Subscribe to a remote component. The first check runs now, so a bad pick fails here."""
    team = _workspace(request)
    if isinstance(team, tuple):
        return team
    try:
        authorize_targets(request, team, payload.product_ids, payload.pin_release_ids)
        server = remote.connect(payload.server)
        subscription = subscribe(
            team,
            Subscribe(
                server=server,
                component_uuid=payload.component_uuid,
                release_uuids=payload.release_uuids,
                tei=payload.tei,
                name=payload.name,
                product_ids=payload.product_ids,
                pin_release_ids=payload.pin_release_ids,
            ),
        )
    except DomainError as error:
        return _fail(error)
    return 201, describe(subscription)


@router.get("/{component_id}", response={200: dict, **ERRORS})
def get_subscription(request: HttpRequest, component_id: str) -> Any:
    """A subscription's status, the remote releases it watches, and their artifacts."""
    subscription = _subscription(request, component_id, "component:read_internal")
    return subscription if isinstance(subscription, tuple) else (200, describe(subscription))


@router.get("/{component_id}/events", response={200: list[EventOut], **ERRORS})
def get_subscription_events(request: HttpRequest, component_id: str) -> Any:
    """What the checks found, newest first."""
    subscription = _subscription(request, component_id, "component:read_internal")
    if isinstance(subscription, tuple):
        return subscription
    return 200, [
        EventOut(kind=e.kind, title=e.get_kind_display(), detail=e.detail, created_at=e.created_at)
        for e in subscription.events.all()[:200]
    ]


@router.post("/{component_id}/check", response={202: dict, **ERRORS}, throttle=OUTBOUND)
def check_subscription(request: HttpRequest, component_id: str) -> Any:
    """Queue a check now."""
    subscription = _subscription(request, component_id, "component:manage")
    if isinstance(subscription, tuple):
        return subscription
    check_tea_subscription.send(subscription.pk, force=True)
    return 202, {"component_id": subscription.component_id, "status": "queued"}


# --- Pins -----------------------------------------------------------------------------------


@router.get("/releases/{release_id}/pins", response={200: list[PinOut], **ERRORS})
def list_pins(request: HttpRequest, release_id: str) -> Any:
    """The remote artifacts a product release pins, with what has happened to each upstream."""
    release = _release(request, release_id, "release:read")
    if isinstance(release, tuple):
        return release
    return 200, [_pin_out(pin) for pin in pins.pins_of(release)]


@router.post(
    "/releases/{release_id}/pins",
    response={201: PinOut, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse, 409: ErrorResponse},
)
def add_pin(request: HttpRequest, release_id: str, payload: PinIn) -> Any:
    """Pin a remote artifact revision into a release, as it is now."""
    release = _release(request, release_id, "release:tag")
    if isinstance(release, tuple):
        return release
    artifact = (
        TeaRemoteArtifact.objects.select_related("release__subscription__component")
        .filter(pk=payload.remote_artifact_id, release__subscription__component__team=release.product.team)
        .first()
    )
    if artifact is None:
        return 404, {"detail": "Remote artifact not found", "error_code": ErrorCode.NOT_FOUND}
    try:
        pin = pins.pin(release, artifact, allow_replacement=payload.allow_replacement)
    except DomainError as error:
        return _fail(error)
    _broadcast_release(release)
    return 201, _pin_out(pin)


@router.delete("/releases/{release_id}/pins/{pin_id}", response={204: None, **ERRORS})
def remove_pin(request: HttpRequest, release_id: str, pin_id: str) -> Any:
    release = _release(request, release_id, "release:manage")
    if isinstance(release, tuple):
        return release
    try:
        pins.unpin(release, pin_id)
    except DomainError as error:
        return _fail(error)
    _broadcast_release(release)
    return 204, None


def _broadcast_release(release: Release) -> None:
    data = {"release_id": str(release.id), "product_id": str(release.product_id), "name": release.name}
    schedule_broadcast(release.product.team.key or "", "release_updated", data)
