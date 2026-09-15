"""Vanta: the spec for the connection, and a thin read client over its API.

Vanta issues one credential per connected customer through the OAuth
authorization-code flow, so every workspace that connects gets its own token
against its own Vanta account. The token endpoint is a single host for every
region; the consent screen is not, which is why ``VANTA_OAUTH_AUTHORIZE_URL``
is a setting rather than a constant (EU and AU customers consent on
``app.eu.vanta.com`` and ``app.aus.vanta.com``).

The client is read-only on purpose. sbomify publishes what Vanta already
knows; it is never the system of record for a control, and nothing here can
write back.
"""

from __future__ import annotations

from typing import Any, Iterator

import requests

from sbomify.apps.core.domain.exceptions import ExternalServiceError
from sbomify.apps.core.integrations.http import request_with_retry
from sbomify.apps.integrations.exceptions import ProviderAuthError
from sbomify.apps.integrations.providers.base import ProviderSpec
from sbomify.logging import getLogger

logger = getLogger(__name__)


class VantaUnavailable(ExternalServiceError):
    """Vanta could not answer. The next scheduled sync tries again."""

    error_code = "vanta_unavailable"


# Vanta caps a page at 100 items. Asking for the cap is what keeps a 300
# control framework to three requests instead of thirty.
PAGE_SIZE = 100

# A framework is a few hundred controls at most, and each one costs a request
# for its status. The ceiling is not a Vanta limit, it is a guard so a
# misconfigured account cannot turn one sync into an unbounded crawl.
MAX_PAGES = 50

VANTA = ProviderSpec(
    key="vanta",
    name="Vanta",
    tagline="Publish the frameworks and controls you already track in Vanta.",
    icon="fa-shield-halved",
    docs_url="https://developer.vanta.com/docs/concepts/authentication",
    reads=(
        "The frameworks your Vanta account tracks",
        "The controls in each framework, and how far each one has got",
    ),
    scopes=("vanta-api.all:read",),
    authorize_url_setting="VANTA_OAUTH_AUTHORIZE_URL",
    exchange_url_setting="VANTA_OAUTH_TOKEN_URL",
    client_id_setting="VANTA_CLIENT_ID",
    client_credential_setting="VANTA_CLIENT_SECRET",
    sync_path="sbomify.apps.integrations.services.vanta_sync.sync",
)


def _results(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Pull one page of items and the next cursor out of a Vanta response.

    Vanta wraps a list in ``results``, with ``data`` and ``pageInfo`` inside
    it. Single-object responses have no wrapper at all. Being tolerant of both
    here means every caller below can treat a page as a plain list.
    """
    if not isinstance(payload, dict):
        return [], None

    results = payload.get("results")
    if not isinstance(results, dict):
        return [], None

    data = results.get("data")
    items = [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    page_info = results.get("pageInfo")
    cursor: str | None = None
    if isinstance(page_info, dict) and page_info.get("hasNextPage"):
        end_cursor = page_info.get("endCursor")
        cursor = end_cursor if isinstance(end_cursor, str) and end_cursor else None

    return items, cursor


class VantaClient:
    """Read calls against one connected Vanta account."""

    def __init__(self, access_token: str, base_url: str) -> None:
        self._access_token = access_token
        self._base_url = base_url.rstrip("/")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            response = request_with_retry(
                "GET",
                url,
                params=params or {},
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/json",
                },
            )
        except requests.RequestException as exc:
            raise VantaUnavailable(f"Could not reach Vanta: {exc}") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthError("Vanta rejected the connection. Reconnect the workspace.", service="vanta")
        if response.status_code >= 400:
            raise VantaUnavailable(f"Vanta returned {response.status_code} for {path}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise VantaUnavailable(f"Vanta returned a non-JSON body for {path}") from exc

        return payload if isinstance(payload, dict) else {}

    def _paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        cursor: str | None = None
        for _page in range(MAX_PAGES):
            page_params = dict(params or {})
            page_params["pageSize"] = PAGE_SIZE
            if cursor:
                page_params["pageCursor"] = cursor

            items, cursor = _results(self._get(path, page_params))
            yield from items

            if not cursor:
                return

        logger.warning("Vanta pagination stopped at %d pages for %s", MAX_PAGES, path)

    def frameworks(self) -> Iterator[dict[str, Any]]:
        """Every framework the connected account tracks."""
        return self._paginate("/v1/frameworks")

    def framework_controls(self, framework_id: str) -> Iterator[dict[str, Any]]:
        """The controls belonging to one framework, without their status."""
        return self._paginate(f"/v1/frameworks/{framework_id}/controls")

    def control(self, control_id: str) -> dict[str, Any]:
        """One control, which is the only place Vanta exposes its status."""
        return self._get(f"/v1/controls/{control_id}")
