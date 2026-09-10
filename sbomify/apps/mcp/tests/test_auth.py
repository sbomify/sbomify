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


@pytest.mark.django_db
def test_a_principal_answers_without_reaching_for_a_token_row(make_token):
    """The four things the server needs about a caller come off the Principal.

    A personal access token is not the only credential this endpoint will
    accept (#1235), and an OAuth caller has no AccessToken row to reach
    through. Holding the facts here rather than the row is what lets the next
    credential fill them without teaching four consumers about it.
    """
    from sbomify.apps.mcp.auth import Principal

    record = make_token(["sbom:read"])
    principal = Principal(
        user=record.user,
        request=fake_request(""),
        workspace=record.team,
        scopes=record.scopes,
        credential_id=str(record.pk),
    )

    assert principal.workspace == record.team
    assert principal.scopes == ["sbom:read"]
    assert principal.credential_id == str(record.pk)
    assert principal.credential_kind == "pat"
    # Optional, and nothing outside auth.py reads it.
    assert principal.token is None


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_pat_fills_every_principal_field(make_token):
    """The PAT path is what proves the shape, rather than a speculative one."""
    from asgiref.sync import sync_to_async

    from sbomify.apps.mcp.auth import authenticate

    token = await sync_to_async(make_token)(["sbom:read"])

    principal = await authenticate(fake_request(f"Bearer {token.encoded_token}"), attempted_action="tools/list")

    assert principal.credential_kind == "pat"
    assert principal.credential_id == str(token.pk)
    assert principal.scopes == ["sbom:read"]
    assert principal.workspace == token.team
    # can() and the rate throttle read this off the stub rather than the
    # Principal, so its contract is the narrower one: .scopes and .pk.
    credential = getattr(principal.request, "access_token_record")
    assert credential.scopes == ["sbom:read"]
    assert credential.pk == token.pk
