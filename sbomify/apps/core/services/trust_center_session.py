"""Signing a reader in on a workspace's own Trust Center host.

A Trust Center is served from the workspace's custom domain or its Trust Center
subdomain, never from the app domain. The session cookie is set on the app
domain, which is where Keycloak sends the reader back after sign-in, and a
browser never sends it anywhere else. So on the Trust Center host every reader
was anonymous: a reader could request access, sign the NDA and be approved, and
still be refused every gated artifact, because the page asking had no idea who
they were.

The app domain therefore hands the signed-in reader over to the Trust Center
host with a token that is short-lived, single-use and bound to that one host.
The session it creates there is *scoped*:

* it is honoured only on the host it was issued for, so a cookie replayed
  anywhere else, the app domain included, is anonymous;
* it only reaches the routes a Trust Center serves (``TRUST_CENTER_ROUTES``),
  so it can read and download, request access and sign the NDA, but never
  reach the app itself;
* it only reaches the workspace that owns the host, so a workspace cannot use
  a reader's session on its own domain to read what another workspace granted
  them.

A workspace controls its own domain's DNS. Everything above is what keeps a
session sbomify set on that domain worth no more there than the reader would
have shown the workspace anyway.
"""

from __future__ import annotations

import secrets
from typing import Any

from django.core import signing
from django.core.cache import cache
from django.http import HttpRequest
from django.urls import Resolver404, resolve

from sbomify.apps.teams.models import Workspace
from sbomify.apps.teams.utils import normalize_host

#: Session key holding the host a Trust Center session was issued for.
SESSION_HOST_KEY = "trust_center_host"

#: How long a handoff token may sit in a redirect before it is refused.
HANDOFF_MAX_AGE_SECONDS = 60

_SALT = "sbomify.trust_center_session.handoff"
_NONCE_CACHE_PREFIX = "trust_center_handoff:"

#: The routes a Trust Center session reaches. Several of the core names are the
#: app's own private pages, which serve their public counterpart on a Trust
#: Center host (see e.g. ``ProductDetailsPrivateView.dispatch``).
TRUST_CENTER_ROUTES = frozenset(
    {
        "core:home",
        "core:logout",
        "core:keycloak_login",
        "core:trust_center_session",
        "core:workspace_public",
        "core:workspace_public_current",
        "core:workspace_advisories_public",
        "core:workspace_advisories_public_current",
        "core:advisory_details_public",
        "core:advisory_details_public_current",
        "core:product_details",
        "core:product_details_public",
        "core:product_releases",
        "core:product_releases_public",
        "core:release_details",
        "core:release_details_public",
        "core:component_details",
        "core:component_details_public",
        "core:component_item",
        "core:component_item_public",
        "core:sbom_download_product",
        "documents:document_download",
        "documents:documents_table_public",
        "documents:request_access",
        "documents:sign_nda",
        "sboms:sbom_download",
        "sboms:sboms_table_public",
        "sboms:sbom_crypto_inventory",
        "sboms:component_crypto_posture",
    }
)


def issue_handoff_token(user: Any, team: Workspace, host: str) -> str:
    """A token that signs ``user`` in on ``host``, once, for the next minute."""
    nonce = secrets.token_urlsafe(16)
    return signing.dumps({"u": user.pk, "w": team.key, "h": host, "n": nonce}, salt=_SALT)


def redeem_handoff_token(token: str, request: HttpRequest) -> int | None:
    """The user id a handoff token was issued for, if it is valid on this request.

    Valid means: signed by us, not expired, issued for this host and the
    workspace that owns it, and never redeemed before. ``None`` otherwise.
    """
    try:
        payload = signing.loads(token, salt=_SALT, max_age=HANDOFF_MAX_AGE_SECONDS)
    except signing.BadSignature:
        return None

    team = getattr(request, "custom_domain_team", None)
    if team is None or payload.get("w") != team.key or payload.get("h") != normalize_host(request.get_host()):
        return None

    # Single use: whoever records the nonce first owns the token. ``add`` is
    # atomic, and outlives the token, so a replay inside the window is refused.
    if not cache.add(f"{_NONCE_CACHE_PREFIX}{payload.get('n')}", True, HANDOFF_MAX_AGE_SECONDS * 2):
        return None

    user_id = payload.get("u")
    return user_id if isinstance(user_id, int) else None


def scoped_session_allows(request: HttpRequest) -> bool:
    """May a Trust Center session act on this request at all?

    Only on the host it was issued for, only on a Trust Center route, and only
    for the workspace that owns the host.
    """
    session = getattr(request, "session", None)
    scoped_host = session.get(SESSION_HOST_KEY) if session is not None else None
    if not scoped_host:
        return True

    team = getattr(request, "custom_domain_team", None)
    if team is None or normalize_host(request.get_host()) != scoped_host:
        return False

    try:
        match = resolve(request.path_info)
    except Resolver404:
        return False
    if match.view_name not in TRUST_CENTER_ROUTES:
        return False

    workspace_key = match.kwargs.get("workspace_key")
    return workspace_key is None or workspace_key == team.key
