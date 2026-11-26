"""Vanta: the spec for the connection, and a thin read client over its API.

Each workspace connects with an application it creates in its own Vanta
account, and pastes that application's client id and secret into sbomify.
That is the only way Vanta grants read access to frameworks and controls:
``vanta-api.all:read`` belongs to "Manage Vanta" applications, which use the
``client_credentials`` grant against the tenant that created them. A partner
app on Vanta's consent screen only gets connector scopes, which push an app's
own resources into Vanta and cannot read a control.

One API and token host serves the US, EU and AU regions, so nothing here
depends on where the customer's account lives.

The client is read-only on purpose. sbomify publishes what Vanta already
knows; it is never the system of record for a control, and nothing here can
write back.
"""

from __future__ import annotations

import time
from typing import Any, Iterator

import requests

from sbomify.apps.core.integrations.http import request_with_retry
from sbomify.apps.integrations.exceptions import ProviderAuthError, ProviderUnavailable
from sbomify.apps.integrations.providers.base import ProviderSpec
from sbomify.logging import getLogger

logger = getLogger(__name__)


class VantaUnavailable(ProviderUnavailable):
    """Vanta could not answer. The next scheduled sync tries again."""

    error_code = "vanta_unavailable"


# Vanta allows a Manage Vanta application 50 requests a minute and answers the
# 51st with a 429 that carries no Retry-After. A sync costs one request per
# control, so an unpaced run trips that limit partway through its first
# framework. Spacing calls a little wider than 60/50 seconds keeps a run under
# it; a 429 that still arrives (another client on the same tenant) is waited
# out a few times before the run gives up for the next schedule.
MIN_REQUEST_INTERVAL = 1.3
RATE_LIMIT_WAIT = 20.0
RATE_LIMIT_ATTEMPTS = 3

# Indirection so tests can stop the clock without patching ``time`` for
# everything else that imports it.
_sleep = time.sleep
_monotonic = time.monotonic

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
    icon="fas fa-shield-halved",
    docs_url="https://developer.vanta.com/docs/quickstart/manage-vanta",
    reads=(
        "The frameworks your Vanta account tracks",
        "The controls in each framework, and how far each one has got",
    ),
    scopes=("vanta-api.all:read",),
    exchange_url_setting="VANTA_OAUTH_TOKEN_URL",
    grant="client_credentials",
    setup_template="integrations/setup/vanta.html.j2",
    client_id_hint="Starts with vci_",
    client_credential_hint="Starts with vcs_. Vanta shows it once, when you generate it.",
    scope_refused_hint=(
        "Vanta accepted that client ID and secret, but the application cannot read controls. It is probably a "
        "Build Integrations application. Create a new application, choose Manage Vanta as its type, and paste "
        "its client ID and secret instead."
    ),
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
        if not isinstance(end_cursor, str) or not end_cursor:
            # Vanta says there is another page and gives nothing to ask for it
            # with. Returning this one as the last page hands the sync a list
            # it would then prune every unfetched framework and control
            # against, and record as a success.
            raise VantaUnavailable("Vanta offered another page with no cursor to fetch it with")
        cursor = end_cursor

    return items, cursor


def _is_list_page(payload: dict[str, Any]) -> bool:
    """Whether ``payload`` is a list page, empty or not: a ``results`` wrapper holding a ``data`` list."""
    results = payload.get("results")
    return isinstance(results, dict) and isinstance(results.get("data"), list)


class VantaClient:
    """Read calls against one connected Vanta account."""

    def __init__(self, access_token: str, base_url: str) -> None:
        self._access_token = access_token
        self._base_url = base_url.rstrip("/")
        self._last_request_at: float | None = None

    def _pace(self) -> None:
        """Wait until the next request fits under Vanta's per-minute limit."""
        if self._last_request_at is not None:
            remaining = MIN_REQUEST_INTERVAL - (_monotonic() - self._last_request_at)
            if remaining > 0:
                _sleep(remaining)
        self._last_request_at = _monotonic()

    def _send(self, url: str, params: dict[str, Any]) -> requests.Response:
        for attempt in range(RATE_LIMIT_ATTEMPTS):
            self._pace()
            try:
                response = request_with_retry(
                    "GET",
                    url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "Accept": "application/json",
                    },
                )
            except requests.RequestException as exc:
                raise VantaUnavailable(f"Could not reach Vanta: {exc}") from exc
            if response.status_code != 429:
                return response
            if attempt + 1 < RATE_LIMIT_ATTEMPTS:
                _sleep(RATE_LIMIT_WAIT)
        raise VantaUnavailable("Vanta kept asking sbomify to slow down. The next scheduled sync tries again.")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        response = self._send(url, params or {})

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

            payload = self._get(path, page_params)
            # A later page that is not a list page is not the end of the list.
            # The earlier pages' items are already the sync's, and ending here
            # would hand it a truncated list to retire frameworks and prune
            # controls against, recorded as a success. The first page keeps the
            # tolerant reading: the sync never prunes against an empty list.
            if cursor and not _is_list_page(payload):
                raise VantaUnavailable(f"Vanta returned a malformed page partway through {path}")
            items, cursor = _results(payload)
            yield from items

            if not cursor:
                return

        # Running out of pages is not "that is all of them". Returning the
        # partial list would let the sync prune every control it did not reach
        # and record the run as a success, so this fails the sync instead.
        raise VantaUnavailable(f"Vanta paged past {MAX_PAGES} pages for {path}")

    def frameworks(self) -> Iterator[dict[str, Any]]:
        """Every framework the connected account tracks."""
        return self._paginate("/v1/frameworks")

    def framework_controls(self, framework_id: str) -> Iterator[dict[str, Any]]:
        """The controls belonging to one framework, without their status."""
        return self._paginate(f"/v1/frameworks/{framework_id}/controls")

    def control(self, control_id: str) -> dict[str, Any]:
        """One control, which is the only place Vanta exposes its status."""
        return self._get(f"/v1/controls/{control_id}")
