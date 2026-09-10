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
