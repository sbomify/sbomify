"""A WebSocket to a path we do not serve is the client's mistake, not a crash.

Channels raises ``ValueError: No route found for path 'wsproxy'`` when nothing
in ``websocket_urlpatterns`` matches, and that exception escapes the whole ASGI
application: uvicorn logs "Exception in ASGI application" with a stack, and the
error tracker files it as a fault of ours. Internet scanners probing paths like
``/wsproxy`` were enough to produce it in production.

Driven through the real ``sbomify.asgi`` application rather than the router in
isolation, because the routing table and the consumer only add up to a fix when
the catch-all is reached in the order the application resolves them.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _connect(path: str) -> list[dict]:
    """Open a WebSocket to ``path`` and return what the server sent back."""
    from sbomify.asgi import application

    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    inbox = [{"type": "websocket.connect"}]

    async def receive() -> dict:
        return inbox.pop(0) if inbox else {"type": "websocket.disconnect", "code": 1000}

    scope = {
        "type": "websocket",
        "path": path,
        "raw_path": path.encode(),
        "headers": [],
        "query_string": b"",
        "subprotocols": [],
    }
    await application(scope, receive, send)
    return sent


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path",
    ["/wsproxy", "/ws/", "/ws/workspace/", "/admin", "/ws/workspace/key/extra/"],
    ids=["the probed path", "bare ws", "no key", "an http path", "a longer ws path"],
)
async def test_an_unrouted_websocket_path_is_refused_rather_than_raising(path) -> None:
    """The defect: this used to raise ``ValueError`` out of the application.

    ``/wsproxy`` is the one seen in production; the rest are near misses of the
    single real route, which is where a routing change is most likely to open
    the hole again.
    """
    from sbomify.apps.core.consumers import WS_CLOSE_POLICY_VIOLATION

    sent = await _connect(path)

    assert [message["type"] for message in sent] == ["websocket.close"]
    assert sent[0].get("code") == WS_CLOSE_POLICY_VIOLATION


@pytest.mark.anyio
async def test_the_catch_all_did_not_swallow_the_real_route() -> None:
    """The risk the fix introduces, which matters more than the fix.

    A catch-all placed or written wrongly answers everything, and the workspace
    socket would then be refused for every client with no error anywhere. The
    real route is unauthenticated here, so it is rejected — but by the consumer
    that read the workspace key out of the URL, which is the thing being
    checked. The catch-all never accepts the handshake, so an accept is proof
    the request reached ``WorkspaceConsumer``.
    """
    sent = await _connect("/ws/workspace/some-key/")

    assert [message["type"] for message in sent] == ["websocket.accept", "websocket.close"]
