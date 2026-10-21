"""The MCP router authenticates and sizes every request before the MCP app reads it.

FastMCP parses the body and validates a call's arguments before any tool code
runs, so a check that lives only in the tool wrapper never sees a malformed or
oversized request. These tests drive ``MCPRouter`` itself.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import pytest
from asgiref.sync import sync_to_async

from sbomify.apps.core.authz import SCOPE_PRESETS
from sbomify.apps.mcp.server import build_app, mcp

LARGE = 2 * 1024 * 1024


def _scope(token: str | None, *, length: int | None = 64) -> dict:
    headers = [(b"host", b"localhost"), (b"content-type", b"application/json")]
    if token is not None:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if length is not None:
        headers.append((b"content-length", str(length).encode()))
    return {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": headers,
        "client": ("203.0.113.9", 4000),
        "server": ("localhost", 80),
        "scheme": "http",
        "http_version": "1.1",
    }


async def _unread_body():
    raise AssertionError("the router read a body it should have refused unread")


class _Recorder:
    """A stand-in MCP app that records the scope each admitted request carried."""

    def __init__(self) -> None:
        self.states: list[dict] = []

    async def __call__(self, scope, receive, send):
        self.states.append(dict(scope.get("state") or {}))
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


async def _drive(app, scope, receive=_unread_body) -> list[dict]:
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    return sent


def _router(mcp_app):
    from sbomify.asgi import MCPRouter

    async def django_app(scope, receive, send):  # pragma: no cover - never reached
        raise AssertionError("an /mcp request reached Django")

    return MCPRouter(django_app, mcp_app)


@asynccontextmanager
async def _routed_mcp_client():
    """An HTTP client for the real MCP app behind the router, as production serves it."""
    build_app()
    mcp._session_manager = None
    app = mcp.streamable_http_app()
    try:
        async with mcp.session_manager.run():
            transport = httpx.ASGITransport(app=_router(app))
            async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
                yield client
    finally:
        mcp._session_manager = None
        mcp.streamable_http_app()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_schema_invalid_call_without_a_token_is_charged_and_audited(monkeypatch):
    """FastMCP refuses bad arguments before the tool wrapper runs, so the door must count it."""
    from sbomify.apps.mcp import auth

    audited: list[tuple] = []
    monkeypatch.setattr(auth, "audit", lambda tool, principal, **kw: audited.append((tool, kw.get("outcome"))))

    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_product", "arguments": {}}}
    async with _routed_mcp_client() as client:
        await client.post(
            "/mcp",
            headers={"content-type": "application/json", "accept": "application/json, text/event-stream"},
            content=json.dumps(body),
        )

    assert [outcome for _, outcome in audited] == ["denied"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_token_over_its_budget_is_refused_before_the_body_is_read(make_token, monkeypatch):
    from sbomify.apps.access_tokens.throttling import AccessTokenRateThrottle

    token = await sync_to_async(make_token)(SCOPE_PRESETS["read_only"])
    monkeypatch.setattr(AccessTokenRateThrottle, "allow_request", lambda self, request: False)
    recorder = _Recorder()

    sent = await _drive(_router(recorder), _scope(token.encoded_token))

    assert recorder.states == []
    assert sent[0]["status"] == 429
    assert "Rate limit exceeded" in json.loads(sent[1]["body"])["error"]["message"]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(("preset", "admitted"), [("read_only", False), ("agent", False), ("publish", True)])
async def test_a_large_body_reaches_the_app_only_from_a_token_that_may_upload(make_token, preset, admitted):
    """Only an upload carries a large body, so nobody else's is read at all."""
    token = await sync_to_async(make_token)(SCOPE_PRESETS[preset])
    recorder = _Recorder()

    sent = await _drive(_router(recorder), _scope(token.encoded_token, length=LARGE))

    if admitted:
        assert len(recorder.states) == 1
    else:
        assert recorder.states == []
        assert sent[0]["status"] == 413


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_large_body_without_a_token_is_refused_unread():
    recorder = _Recorder()

    sent = await _drive(_router(recorder), _scope(None, length=LARGE))

    assert recorder.states == []
    assert sent[0]["status"] == 413


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_body_of_unstated_size_is_refused_unless_the_token_may_upload(make_token):
    token = await sync_to_async(make_token)(SCOPE_PRESETS["agent"])
    scope = _scope(token.encoded_token, length=None)
    scope["headers"].append((b"transfer-encoding", b"chunked"))
    recorder = _Recorder()

    sent = await _drive(_router(recorder), scope)

    assert recorder.states == []
    assert sent[0]["status"] == 413


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_call_through_the_door_charges_the_token_once(make_token, monkeypatch):
    """The door authenticates; the tool wrapper reuses that answer instead of charging again."""
    from sbomify.apps.access_tokens.throttling import AccessTokenRateThrottle

    token = await sync_to_async(make_token)(None)
    checks: list[int] = []
    original = AccessTokenRateThrottle.allow_request

    def counting(self, request):
        checks.append(1)
        return original(self, request)

    monkeypatch.setattr(AccessTokenRateThrottle, "allow_request", counting)

    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "get_workspace_summary", "arguments": {}},
    }
    async with _routed_mcp_client() as client:
        response = await client.post(
            "/mcp",
            headers={
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
                "authorization": f"Bearer {token.encoded_token}",
            },
            content=json.dumps(body),
        )

    assert response.status_code == 200
    assert json.loads(response.text)["result"].get("isError") is not True
    assert len(checks) == 1


class _Reader:
    """A stand-in MCP app that reads the whole body, as the transport does, then answers."""

    def __init__(self) -> None:
        self.read = 0

    async def __call__(self, scope, receive, send):
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            self.read += len(message.get("body", b""))
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


def _body(total: int, chunk: int = 64 * 1024):
    """A receive callable that streams ``total`` bytes in chunks, as an HTTP/2 client may."""
    sent = 0

    async def receive():
        nonlocal sent
        size = min(chunk, total - sent)
        sent += size
        return {"type": "http.request", "body": b"x" * size, "more_body": sent < total}

    return receive


def _h2_scope(token: str | None) -> dict:
    """HTTP/2 needs neither Content-Length nor Transfer-Encoding to carry a body."""
    scope = _scope(token, length=None)
    scope["http_version"] = "2"
    return scope


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_body_of_no_stated_length_is_cut_off_at_the_cap_as_it_arrives(make_token, settings):
    """The headers cannot size an HTTP/2 body, so the bytes are counted as they come in."""
    token = await sync_to_async(make_token)(SCOPE_PRESETS["agent"])
    reader = _Reader()

    sent = await _drive(_router(reader), _h2_scope(token.encoded_token), _body(3 * settings.MCP_MAX_REQUEST_BYTES))

    assert sent[0]["status"] == 413
    assert reader.read <= settings.MCP_MAX_REQUEST_BYTES


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_small_body_of_no_stated_length_still_goes_through(make_token):
    token = await sync_to_async(make_token)(SCOPE_PRESETS["agent"])
    reader = _Reader()

    sent = await _drive(_router(reader), _h2_scope(token.encoded_token), _body(200))

    assert sent[0]["status"] == 200
    assert reader.read == 200


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_an_upload_of_no_stated_length_goes_through_up_to_the_upload_cap(make_token):
    token = await sync_to_async(make_token)(SCOPE_PRESETS["publish"])
    reader = _Reader()

    sent = await _drive(_router(reader), _h2_scope(token.encoded_token), _body(LARGE))

    assert sent[0]["status"] == 200
    assert reader.read == LARGE


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_the_real_transport_answers_413_when_the_body_is_cut_off(make_token, settings):
    token = await sync_to_async(make_token)(SCOPE_PRESETS["agent"])
    build_app()
    mcp._session_manager = None
    app = mcp.streamable_http_app()
    scope = _h2_scope(token.encoded_token)
    scope["headers"].append((b"accept", b"application/json, text/event-stream"))
    try:
        async with mcp.session_manager.run():
            sent = await _drive(_router(app), scope, _body(3 * settings.MCP_MAX_REQUEST_BYTES))
    finally:
        mcp._session_manager = None
        mcp.streamable_http_app()

    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert [m["status"] for m in starts] == [413]
