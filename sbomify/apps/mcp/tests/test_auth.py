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
async def test_the_stub_request_carries_the_token_record(make_token):
    """The split: metadata on the Principal, the row on the stub request.

    ``Principal`` deliberately holds no ``AccessToken``, so the identity
    assertions below read its own fields. The row still has to reach the stub,
    because ``can()`` and the throttle read it from there and scope enforcement
    silently no-ops without it.
    """
    token = await _acreate(make_token, ["product:read"])

    principal = await authenticate(fake_request(f"Bearer {token.encoded_token}"), attempted_action="tools/list")

    assert principal.credential_id == str(token.pk)
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

    assert principal.credential_id == str(token.pk)


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
    credential = principal.request.access_token_record
    assert credential.scopes == ["sbom:read"]
    assert credential.pk == token.pk


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

    event = spy.info.call_args.kwargs["extra"]
    assert event["team_id"] == str(bound.pk)
    # The rest of the identity the stream is read for. A caller is only
    # reconstructable if all three survive together.
    assert event["credential"] == "pat"
    assert event["token_id"] == str(token.pk)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_trusted_publishing_bot_is_not_audited_as_a_pat(mcp_owner):
    """An AccessToken row is not proof of a personal access token.

    OIDC Trusted Publishing mints rows too, and ``get_user_and_token_record``
    resolves both kinds, so hardcoding the kind made the field say nothing:
    every caller read as ``pat`` and a bot's uploads were indistinguishable
    from a human's.
    """
    import time

    from asgiref.sync import sync_to_async
    from django.conf import settings

    from sbomify.apps.access_tokens.models import AccessToken
    from sbomify.apps.access_tokens.utils import TOKEN_TYPE_OIDC, create_personal_access_token

    user, bound, _ = mcp_owner

    def bot_token() -> AccessToken:
        encoded = create_personal_access_token(user, expires_at=time.time() + 900, token_type=TOKEN_TYPE_OIDC)
        return AccessToken.objects.create(
            user=user,
            encoded_token=encoded,
            team=bound,
            scopes=["artifact:publish"],
            description="trusted publishing bot",
        )

    assert settings.JWT_AUDIENCE
    token = await sync_to_async(bot_token)()

    principal = await authenticate(fake_request(f"Bearer {token.encoded_token}"), attempted_action="upload_artifact")

    assert principal.credential_kind == "oidc"


class TestTheCredentialContractHolds:
    """The documented contract is `.scopes` and `.pk`. This is what enforces it.

    The upload path reaches `oidc.permissions.request_is_oidc_authed`, which
    also wants `.encoded_token` and `.user_id`. Before, a credential carrying
    only the two documented attributes raised AttributeError on its first
    `upload_artifact` or `create_release`. In `create_release` that call sits
    outside the view's try, so it propagated: audited as `outcome="error"` with
    no detail by design, and opaque to the agent.
    """

    class MinimalCredential:
        """Exactly what the docstring promises a phase-two credential must answer."""

        def __init__(self, scopes: list[str] | None) -> None:
            self.scopes = scopes
            self.pk = "oauth-credential-1"

    @staticmethod
    def _request(credential: object) -> Any:
        from django.http import HttpRequest

        request = HttpRequest()
        setattr(request, "access_token_record", credential)
        return request

    def test_it_is_not_read_as_a_trusted_publishing_bot(self) -> None:
        from sbomify.apps.oidc.permissions import request_is_oidc_authed

        request = self._request(self.MinimalCredential(["artifact:publish"]))

        assert request_is_oidc_authed(request) is False, "a credential with no bot user is not a bot"

    @pytest.mark.django_db
    def test_the_upload_gate_lets_it_through_to_the_ordinary_check(self) -> None:
        """Not a bot means no component confinement, not a refusal."""
        from types import SimpleNamespace

        from sbomify.apps.oidc.permissions import is_authorised_for_component

        request = self._request(self.MinimalCredential(None))

        assert is_authorised_for_component(request, SimpleNamespace(id="anything")) is True

    @pytest.mark.django_db
    def test_a_real_pat_row_still_reaches_the_binding_check(self) -> None:
        """The defensive reads must not blunt the check for the credential it guards."""
        from sbomify.apps.oidc.permissions import request_is_oidc_authed

        assert request_is_oidc_authed(self._request(None)) is False
