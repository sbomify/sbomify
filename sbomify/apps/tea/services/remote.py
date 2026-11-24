"""Reading another TEA server: where its API is, whether sbomify may connect, and what it lists.

Every server address here comes from a user, and sbomify's own servers make the
requests, so an address is checked before every client built for it. That
includes the API base a server's ``.well-known/tea`` advertises: libtea checks
neither it nor the domain it was fetched from.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Any, TypeVar
from urllib.parse import urlsplit

from django.conf import settings
from libtea import TeaClient
from libtea.discovery import fetch_well_known, parse_tei, select_best_endpoint
from libtea.exceptions import TeaConnectionError, TeaDiscoveryError, TeaError, TeaNotFoundError, TeaServerError
from libtea.models import Collection, Identifier

from sbomify.apps.core.domain.exceptions import ExternalServiceError, NotFoundError, ValidationError
from sbomify.apps.core.net import is_public_address

log = logging.getLogger(__name__)

TEA_VERSION = "1.0.0"
TIMEOUT = 15.0
MAX_RETRIES = 1
# Most components a product release preview reads, one collection each.
PREVIEW_LIMIT = 25
# Names that reach cloud metadata or cluster services without a link-local address.
BLOCKED_HOSTS = frozenset({"metadata", "metadata.google.internal", "instance-data", "kubernetes.default.svc"})
_VERSIONED_BASE = re.compile(r"/v(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]*)?)$")
_LEGACY_REFUSED = "This server speaks TEA {offered}. sbomify subscribes to TEA 1.0 servers only."

_T = TypeVar("_T")


@dataclass(frozen=True)
class RemoteServer:
    """A TEA 1.0 API base sbomify may read, such as ``https://host/tea/v1.0.0``."""

    base_url: str
    spec_version: str

    def client(self) -> TeaClient:
        check_address(self.base_url)
        return TeaClient(self.base_url, timeout=TIMEOUT, max_retries=MAX_RETRIES, spec_version=self.spec_version)


@dataclass(frozen=True)
class Page:
    items: list[dict[str, Any]]
    next_page_token: str | None = None


@dataclass(frozen=True)
class TeiMatch:
    server: RemoteServer
    product_release_uuids: list[str] = field(default_factory=list)


def check_address(url: str) -> None:
    """Refuse an address sbomify should not connect to on a user's behalf."""
    allow_private = settings.TEA_SUBSCRIPTION_ALLOW_PRIVATE_HOSTS
    parts = urlsplit(url)
    if parts.scheme != "https" and not (allow_private and parts.scheme == "http"):
        raise ValidationError("Use an https address.")
    host = (parts.hostname or "").rstrip(".").lower()
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise ValidationError("That is not a server address.") from exc
    if not host or parts.username or parts.password:
        raise ValidationError("That is not a server address.")
    if host in BLOCKED_HOSTS:
        raise ValidationError("sbomify does not connect to that address.")
    try:
        resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise ExternalServiceError(f"No server answers at {host}.", service="tea") from exc
    for *_, sockaddr in resolved:
        address = ipaddress.ip_address(sockaddr[0])
        # Link-local covers the cloud metadata addresses, which stay refused in development too.
        if address.is_link_local or not (allow_private or is_public_address(address)):
            raise ValidationError("sbomify only connects to servers on the public internet.")


def connect(server: str) -> RemoteServer:
    """The TEA 1.0 API of what a user typed: a domain, or an API base ending in its version."""
    text = server.strip().rstrip("/")
    if not text:
        raise ValidationError("Enter a server.")
    if "://" not in text:
        return _from_domain(text)
    match = _VERSIONED_BASE.search(urlsplit(text).path)
    if match is None:
        raise ValidationError("Give the API base with its version, like https://example.com/tea/v1.0.0, or the domain.")
    if not match["version"].startswith("1."):
        raise ValidationError(_LEGACY_REFUSED.format(offered=match["version"]))
    check_address(text)
    return RemoteServer(text, match["version"])


def _from_domain(domain: str) -> RemoteServer:
    host, _, port_text = domain.partition(":")
    if port_text and not port_text.isdigit():
        raise ValidationError("That is not a server address.")
    check_address(f"https://{domain}/")
    try:
        well_known = fetch_well_known(host, timeout=TIMEOUT, port=int(port_text) if port_text else None)
    except TeaDiscoveryError as exc:
        log.info("No TEA discovery document at %s: %s", domain, exc)
        raise ExternalServiceError(f"{domain} publishes no TEA discovery document.", service="tea") from exc
    offered = sorted({version for endpoint in well_known.endpoints for version in endpoint.versions})
    try:
        best = select_best_endpoint(well_known, TEA_VERSION)
    except TeaDiscoveryError as exc:
        raise ValidationError(_LEGACY_REFUSED.format(offered=", ".join(offered))) from exc
    base_url = f"{best.endpoint.url}/v{best.matched_version}"
    check_address(base_url)
    return RemoteServer(base_url, best.matched_version)


def read(call: Callable[[], _T]) -> _T:
    """Run one remote read, turning libtea's errors into ones a page or the API can answer with."""
    try:
        return call()
    except TeaNotFoundError as exc:
        raise NotFoundError("The server has no such item.") from exc
    except (TeaConnectionError, TeaServerError) as exc:
        log.info("TEA server unreachable: %s", exc)
        raise ExternalServiceError("The server did not answer. Try again later.", service="tea") from exc
    except TeaError as exc:
        log.info("TEA server answer refused: %s", exc)
        raise ExternalServiceError("The server's answer is not valid TEA 1.0.", service="tea") from exc


def resolve_tei(tei: str) -> TeiMatch:
    """The server a TEI names, found through its own domain, and the product releases it resolves to there."""
    try:
        _type, domain, _identifier = parse_tei(tei.strip())
    except TeaDiscoveryError as exc:
        raise ValidationError("That is not a TEI.") from exc
    server = connect(domain)
    with server.client() as client:
        results = read(lambda: client.discover(tei.strip()))
    uuids = [result.product_release_uuid for result in results]
    for result in results:
        for listed in result.servers:
            version = next((v for v in listed.versions if v.startswith("1.")), None)
            if version is not None:
                server = RemoteServer(f"{listed.root_url.rstrip('/')}/v{version}", version)
                check_address(server.base_url)
                return TeiMatch(server, uuids)
    return TeiMatch(server, uuids)


def identifiers(values: tuple[Identifier, ...]) -> list[dict[str, str]]:
    return [{"id_type": str(i.id_type), "id_value": i.id_value or ""} for i in values]


def preview(collection: Collection | None) -> list[dict[str, Any]]:
    """What a collection holds, by name, type and format, without fetching any artifact."""
    if collection is None:
        return []
    return [
        {
            "uuid": artifact.uuid,
            "name": artifact.name or artifact.uuid,
            "type": str(artifact.type),
            "formats": [fmt.media_type or "" for fmt in artifact.formats],
        }
        for artifact in collection.artifacts
    ]


def list_products(
    server: RemoteServer, *, id_type: str | None = None, id_value: str | None = None, page_token: str | None = None
) -> Page:
    with server.client() as client:
        if id_type and id_value:
            page = read(lambda: client.search_products(id_type, id_value, page_token=page_token, page_size=25))
        else:
            page = read(lambda: client.list_products(page_token=page_token, page_size=25))
    items = [{"uuid": p.uuid, "name": p.name, "identifiers": identifiers(p.identifiers)} for p in page.results]
    return Page(items, page.next_page_token)


def product_releases(server: RemoteServer, product_uuid: str, *, page_token: str | None = None) -> Page:
    with server.client() as client:
        page = read(lambda: client.get_product_releases(product_uuid, page_token=page_token, page_size=25))
    items = [
        {
            "uuid": r.uuid,
            "version": r.version,
            "product_name": r.product_name or "",
            "release_date": r.release_date or r.created_date,
            "pre_release": bool(r.pre_release),
        }
        for r in page.results
    ]
    return Page(items, page.next_page_token)


def product_release_components(server: RemoteServer, product_release_uuid: str) -> dict[str, Any]:
    """A product release's components, each with the component release it ships and that release's latest collection."""
    with server.client() as client:
        release = read(lambda: client.get_product_release(product_release_uuid))
        components = []
        for ref in release.components[:PREVIEW_LIMIT]:
            component = read(partial(client.get_component, ref.uuid))
            collection = None
            if ref.release:
                try:
                    collection = read(partial(client.get_component_release_collection_latest, ref.release))
                except NotFoundError:
                    collection = None
            components.append(
                {
                    "uuid": component.uuid,
                    "name": component.name,
                    "identifiers": identifiers(component.identifiers),
                    "release_uuid": ref.release or "",
                    "artifacts": preview(collection),
                }
            )
    return {
        "uuid": release.uuid,
        "version": release.version,
        "product_name": release.product_name or "",
        "components": components,
        "truncated": len(release.components) > PREVIEW_LIMIT,
    }


def component_releases(server: RemoteServer, component_uuid: str) -> list[dict[str, Any]]:
    with server.client() as client:
        releases = read(lambda: client.get_component_releases(component_uuid))
    return [
        {
            "uuid": r.uuid,
            "version": r.version,
            "release_date": r.release_date or r.created_date,
            "pre_release": bool(r.pre_release),
        }
        for r in releases
    ]
