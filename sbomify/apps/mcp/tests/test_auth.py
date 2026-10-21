"""Bearer-token authentication for the MCP server.

Covers the adapter that turns a Starlette request into the stub ``HttpRequest``
that ``can()`` reads. If the stub loses ``access_token_record``, scope
enforcement silently stops happening — so that is asserted explicitly.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sbomify.apps.mcp.auth import MCPAuthError, authenticate, require


def fake_request(authorization: str | None = None, *, client_host: str = "10.1.2.3") -> SimpleNamespace:
    """A stand-in for the Starlette request the transport hands to a tool."""
    headers = {} if authorization is None else {"authorization": authorization}
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host=client_host),
        url=SimpleNamespace(path="/mcp"),
    )


@pytest.mark.asyncio
async def test_missing_authorization_header_is_rejected():
    with pytest.raises(MCPAuthError, match="Missing bearer token"):
        await authenticate(fake_request(), attempted_action="tools/list")


@pytest.mark.asyncio
async def test_non_bearer_scheme_is_rejected():
    with pytest.raises(MCPAuthError, match="Missing bearer token"):
        await authenticate(fake_request("Basic abc123"), attempted_action="tools/list")


@pytest.mark.asyncio
async def test_empty_bearer_token_is_rejected():
    with pytest.raises(MCPAuthError, match="Missing bearer token"):
        await authenticate(fake_request("Bearer   "), attempted_action="tools/list")


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", [None, "Basic abc123", "Bearer   "], ids=["none", "basic", "empty"])
async def test_a_request_without_a_usable_bearer_token_is_charged_to_its_address(authorization, settings):
    """Refusing before the per-IP budget is checked would leave every request
    that sends no usable token free of any limit at all."""
    from django.core.cache import cache

    from sbomify.apps.mcp.auth import MCPRateLimitedError

    cache.clear()
    settings.API_ANONYMOUS_RATE_LIMIT = "2/min"
    request = fake_request(authorization, client_host="10.9.9.9")

    for _ in range(2):
        with pytest.raises(MCPAuthError, match="Missing bearer token"):
            await authenticate(request, attempted_action="tools/list")
    with pytest.raises(MCPRateLimitedError):
        await authenticate(request, attempted_action="tools/list")


def _audit_events(spy) -> list[dict]:
    """The mcp_tool_call events a patched ``limits.log`` received."""
    calls = spy.method_calls
    return [c.kwargs["extra"] for c in calls if c.kwargs.get("extra", {}).get("event") == "mcp_tool_call"]


@pytest.mark.asyncio
@pytest.mark.django_db
@pytest.mark.parametrize(
    "authorization",
    [None, "Basic abc123", "Bearer   ", "Bearer not-a-real-token"],
    ids=["none", "basic", "empty", "unknown-token"],
)
async def test_every_refused_credential_is_audited_once_without_its_secret(authorization, settings):
    """A refusal raised before the tool wrapper's audit block left unauthenticated
    probing out of the MCP audit stream entirely."""
    from unittest.mock import patch

    from django.core.cache import cache

    from sbomify.apps.mcp import limits

    cache.clear()
    settings.API_ANONYMOUS_RATE_LIMIT = "100/min"

    with patch.object(limits, "log") as spy, pytest.raises(MCPAuthError):
        await authenticate(fake_request(authorization, client_host="10.7.7.7"), attempted_action="list_products")

    [event] = _audit_events(spy)
    assert event["tool"] == "list_products"
    assert event["outcome"] == "denied"
    assert event["client_ip"] == "10.7.7.7"
    assert event["token_id"] is None
    logged = repr(spy.method_calls)
    assert "not-a-real-token" not in logged
    assert "abc123" not in logged


@pytest.mark.asyncio
async def test_a_refusal_over_the_address_budget_is_audited_as_rate_limited(settings):
    from unittest.mock import patch

    from django.core.cache import cache

    from sbomify.apps.mcp import limits
    from sbomify.apps.mcp.auth import MCPRateLimitedError

    cache.clear()
    settings.API_ANONYMOUS_RATE_LIMIT = "1/min"
    request = fake_request(None, client_host="10.8.8.8")
    with pytest.raises(MCPAuthError):
        await authenticate(request, attempted_action="tools/list")

    with patch.object(limits, "log") as spy, pytest.raises(MCPRateLimitedError):
        await authenticate(request, attempted_action="tools/list")

    [event] = _audit_events(spy)
    assert event["outcome"] == "rate_limited"
    assert event["client_ip"] == "10.8.8.8"


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_garbage_token_is_rejected():
    with pytest.raises(MCPAuthError, match="Invalid or expired"):
        await authenticate(fake_request("Bearer not-a-real-token"), attempted_action="tools/list")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_valid_token_yields_principal_carrying_the_token_record(make_token):
    """The stub request must carry the token record, or scope checks no-op."""
    token = await _acreate(make_token, ["product:read"])

    principal = await authenticate(fake_request(f"Bearer {token.encoded_token}"), attempted_action="tools/list")

    assert principal.token.pk == token.pk
    assert principal.scopes == ["product:read"]
    assert getattr(principal.request, "access_token_record", None) is not None
    assert getattr(principal.request, "token_team", None) is not None
    # An empty session, mirroring authz._stub_request_for_user: nothing may be
    # granted by session state on this path.
    assert principal.request.session == {}


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_bearer_scheme_is_case_insensitive(make_token):
    """RFC 7235: a lowercased scheme must not bypass authentication."""
    token = await _acreate(make_token, None)

    principal = await authenticate(fake_request(f"bearer {token.encoded_token}"), attempted_action="tools/list")

    assert principal.token.pk == token.pk


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_client_ip_is_taken_from_the_connection(make_token):
    token = await _acreate(make_token, None)

    principal = await authenticate(
        fake_request(f"Bearer {token.encoded_token}", client_host="10.9.9.9"),
        attempted_action="tools/list",
    )

    assert principal.request.META["REMOTE_ADDR"] == "10.9.9.9"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_require_denies_action_outside_token_scope(make_token, mcp_owner):
    """The scope gate must fire even though the user is a workspace owner."""
    from asgiref.sync import sync_to_async

    _, bound, _ = mcp_owner
    token = await _acreate(make_token, ["product:read"])
    principal = await authenticate(fake_request(f"Bearer {token.encoded_token}"), attempted_action="upload_artifact")

    # In scope: allowed.
    await sync_to_async(require)(principal, "product:read", bound)

    # Out of scope: denied despite the owner role.
    with pytest.raises(MCPAuthError, match="token scope does not grant"):
        await sync_to_async(require)(principal, "artifact:publish", bound)


async def _acreate(make_token, scopes):
    from asgiref.sync import sync_to_async

    return await sync_to_async(make_token)(scopes)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_the_audit_line_names_the_workspace_the_call_ran_in(make_token, mcp_owner):
    """A legacy token has no workspace of its own, but its calls still land in one.

    ``AccessToken.team`` is nullable, and ``resolve_workspace`` falls back to
    the user's default. Auditing the token's own field recorded null for every
    one of those reads and writes, so the stream said a workspace-less token
    did work in no workspace at all.
    """
    from unittest.mock import patch

    from asgiref.sync import sync_to_async

    from sbomify.apps.access_tokens.models import AccessToken
    from sbomify.apps.access_tokens.utils import create_personal_access_token
    from sbomify.apps.mcp import limits
    from sbomify.apps.mcp.tools._base import resolve_workspace

    user, bound, _ = mcp_owner

    def legacy() -> AccessToken:
        return AccessToken.objects.create(
            user=user,
            encoded_token=create_personal_access_token(user),
            team=None,
            scopes=["workspace:read"],
            description="pre-workspace-scoping token",
        )

    token = await sync_to_async(legacy)()
    principal = await authenticate(fake_request(f"Bearer {token.encoded_token}"), attempted_action="tools/list")

    assert token.team_id is None
    resolved = await sync_to_async(resolve_workspace)(principal)
    assert resolved.pk == bound.pk

    with patch.object(limits, "log") as spy:
        await sync_to_async(limits.audit)("get_workspace_summary", principal, outcome="success")

    assert spy.info.call_args.kwargs["extra"]["team_id"] == str(bound.pk)
