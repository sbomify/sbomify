"""End-to-end tests over the real streamable-HTTP transport.

These drive the ASGI app the way a client does, which is the only way to catch
two failure modes that unit tests cannot see:

* the session manager's task group not being started (every request fails with
  "Task group is not initialized"), and
* scope-based filtering of ``tools/list``, which reads the bearer token from the
  live request rather than from an injected principal.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import pytest
from asgiref.sync import sync_to_async

from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.mcp.server import build_app, mcp

# localhost is in the SDK's DNS-rebinding allow-list, so tests exercise the same
# middleware production does rather than bypassing it.
MCP_URL = "http://localhost/mcp"
HEADERS = {
    "content-type": "application/json",
    "accept": "application/json, text/event-stream",
}


@asynccontextmanager
async def mcp_http():
    """An HTTP client bound to the MCP app, with a running session manager.

    Entering ``session_manager.run()`` mirrors what ``LifespanApp`` does in
    ``sbomify/asgi.py``; without it every request fails with "Task group is not
    initialized".

    Deliberately a context manager used inside each test rather than a fixture:
    the manager's task group is an anyio cancel scope, which must be entered and
    exited in the *same* task, and pytest-asyncio drives async-generator fixture
    setup and teardown from different tasks.

    Each test also gets a fresh manager, since one may only be run once — that is
    the SDK's own advice ("Create a new instance if you need to run again").
    ``build_app()`` has already registered the tools by this point, so clearing
    the cached manager only rebuilds the transport.

    The ``finally`` leaves a fresh, unused manager cached. ``mcp`` is a
    module-level singleton, so without it these tests would hand the next
    consumer a spent manager — which is exactly what broke
    ``core.tests.test_asgi`` when the full suite ran both.
    """
    build_app()
    mcp._session_manager = None
    app = mcp.streamable_http_app()

    try:
        async with mcp.session_manager.run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
                yield client
    finally:
        mcp._session_manager = None
        mcp.streamable_http_app()


def structured(response: httpx.Response) -> dict:
    """The tool's return value.

    Every tool returns (and is annotated as returning) a dict, so FastMCP's
    output schema is the dict itself — ``structuredContent`` carries the tool's
    return value directly, with no extra nesting.
    """
    payload = parse(response)
    assert payload["result"].get("isError") is not True, payload
    return payload["result"]["structuredContent"]


async def call(client: httpx.AsyncClient, method: str, token: str | None = None, **params):
    headers = dict(HEADERS)
    if token is not None:
        headers["authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params:
        body["params"] = params
    response = await client.post(MCP_URL, headers=headers, content=json.dumps(body))
    return response


def parse(response: httpx.Response) -> dict:
    """Read a JSON-RPC result from either a JSON or an SSE-framed response."""
    text = response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        for line in text.splitlines():
            if line.startswith("data: "):
                return json.loads(line[6:])
        raise AssertionError(f"no data frame in SSE response: {text!r}")
    return json.loads(text)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_tools_list_succeeds_over_the_transport(make_token):
    """Guards the lifespan wiring: without it this fails with a task-group error.

    Uses a full-capability token because an unauthenticated caller is
    deliberately offered nothing — see ``test_security``.
    """
    token = await sync_to_async(make_token)(None)

    async with mcp_http() as client:
        response = await call(client, "tools/list", token=token.encoded_token)

        assert response.status_code == 200, response.text
        payload = parse(response)
        assert "error" not in payload, payload
        names = {tool["name"] for tool in payload["result"]["tools"]}
        assert "list_products" in names


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_tools_list_is_filtered_to_a_read_only_tokens_scopes(make_token):
    async with mcp_http() as client:
        token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

        response = await call(client, "tools/list", token=token.encoded_token)

        names = {tool["name"] for tool in parse(response)["result"]["tools"]}
        assert "list_products" in names
        assert "upload_sbom" not in names
        assert "create_release" not in names


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_tools_list_is_filtered_to_a_publish_tokens_scopes(make_token):
    async with mcp_http() as client:
        token = await sync_to_async(make_token)(SCOPE_PRESETS["publish"])

        response = await call(client, "tools/list", token=token.encoded_token)

        names = {tool["name"] for tool in parse(response)["result"]["tools"]}
        assert "upload_sbom" in names
        assert "list_products" not in names
        # VEX needs the stricter artifact:publish_vex, absent from this preset.
        assert "upload_vex" not in names


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_calling_a_tool_without_a_token_is_rejected():
    async with mcp_http() as client:
        response = await call(client, "tools/call", name="list_products", arguments={})

        payload = parse(response)
        text = json.dumps(payload)
        assert "Missing bearer token" in text, text


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_read_token_can_list_products(make_token, product_in_bound_workspace):
    async with mcp_http() as client:
        token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

        response = await call(client, "tools/call", token=token.encoded_token, name="list_products", arguments={})

        result = structured(response)
        assert result["total"] == 1
        assert result["items"][0]["name"] == "Bound Product"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_tool_outside_the_tokens_scope_is_denied_even_though_it_was_hidden(make_token):
    """Hiding a tool is ergonomics; the call must still be refused on its merits."""
    async with mcp_http() as client:
        token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

        response = await call(
            client,
            "tools/call",
            token=token.encoded_token,
            name="create_release",
            arguments={"product_id": "whatever", "name": "v1"},
        )

        text = json.dumps(parse(response))
        assert "Not permitted" in text or "No product found" in text, text


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_workspace_isolation(make_token, product_in_other_workspace):
    """A token pinned to workspace A must not read workspace B's products."""
    async with mcp_http() as client:
        token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

        listed = await call(client, "tools/call", token=token.encoded_token, name="list_products", arguments={})
        fetched = await call(
            client,
            "tools/call",
            token=token.encoded_token,
            name="get_product",
            arguments={"product_id": product_in_other_workspace.id},
        )

        assert structured(listed)["total"] == 0
        assert "No product found" in json.dumps(parse(fetched))


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_page_size_is_clamped(make_token, product_in_bound_workspace):
    """An agent asking for 10_000 rows must not get them."""
    async with mcp_http() as client:
        token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])

        response = await call(
            client,
            "tools/call",
            token=token.encoded_token,
            name="list_products",
            arguments={"page_size": 10_000},
        )

        assert structured(response)["page_size"] == 100


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_throttled_tools_list_is_an_error_not_an_empty_catalogue(make_token, monkeypatch):
    """Clients cache the handshake's tool list, so a transient rate limit must
    surface as a retryable error — an empty list would read as "this server has
    no tools" and stick for the rest of the session."""
    from sbomify.apps.access_tokens.throttling import AccessTokenRateThrottle

    token = await sync_to_async(make_token)(None)
    monkeypatch.setattr(AccessTokenRateThrottle, "allow_request", lambda self, request: False)

    async with mcp_http() as client:
        response = await call(client, "tools/list", token=token.encoded_token)

    payload = parse(response)
    assert "error" in payload, payload
    assert "tools" not in json.dumps(payload.get("result", {}))


def test_transport_body_cap_clears_the_upload_limit():
    """The SDK's default transport cap is 4 MiB — smaller than the artifact
    limit, which would reject a container SBOM before enforce_upload_size ever
    saw it and turn MCP_MAX_UPLOAD_BYTES into dead configuration."""
    from sbomify.apps.mcp.limits import MAX_UPLOAD_BYTES

    assert mcp.settings.max_request_body_size >= 2 * MAX_UPLOAD_BYTES
