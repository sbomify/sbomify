"""OAuth on /mcp: Keycloak signs the token, the server checks it was signed for /mcp.

The realm's signing keys are replaced with a key generated here, so these
cover what sbomify decides: the audience, the person a token resolves to, the
read-only reach of an OAuth session, and the 401 that starts a client's
sign-in.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from allauth.socialaccount.models import SocialAccount
from asgiref.sync import sync_to_async
from cryptography.hazmat.primitives.asymmetric import rsa

from sbomify.apps.mcp import oauth, registry
from sbomify.apps.mcp.auth import MCPAuthError, authenticate

from .test_auth import fake_request
from .test_door import _drive, _Recorder, _router, _scope
from .test_protocol import call, mcp_http, parse

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _RealmKeys:
    """Keycloak's key set, as the one key these tests sign with, counting forced fetches."""

    def __init__(self) -> None:
        self.forced_fetches = 0

    def get_signing_keys(self, refresh: bool = False) -> list[SimpleNamespace]:
        self.forced_fetches += refresh
        return [SimpleNamespace(key_id="test", key=KEY.public_key())]


@pytest.fixture(autouse=True)
def realm_keys(monkeypatch):
    from django.core.cache import cache

    cache.delete(oauth._JWKS_REFRESH_MARKER)
    keys = _RealmKeys()
    monkeypatch.setattr(oauth, "_jwks_client", lambda: keys)
    return keys


def _token(sub: str = "kc-user-1", kid: str = "test", **claims) -> str:
    now = int(time.time())
    payload = {
        "iss": oauth.issuer(),
        "aud": oauth.resource(),
        "sub": sub,
        "iat": now,
        "exp": now + 300,
        "scope": "openid email mcp",
        **claims,
    }
    return jwt.encode(payload, KEY, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def signed_in(mcp_owner):
    """The workspace owner, who has signed in to sbomify through Keycloak once."""
    user, _, _ = mcp_owner
    SocialAccount.objects.create(user=user, provider="keycloak", uid="kc-user-1")
    return user


def test_the_metadata_names_the_realm_and_this_server(client):
    response = client.get(oauth.METADATA_PATH)

    assert response.status_code == 200
    assert response.json()["resource"] == oauth.resource()
    assert response.json()["authorization_servers"] == [oauth.issuer()]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(("token", "invalid"), [(None, False), ("not-a-real-token", True)])
async def test_a_request_without_a_usable_token_is_challenged(token, invalid):
    recorder = _Recorder()

    sent = await _drive(_router(recorder), _scope(token))

    assert recorder.states == [], "the MCP app never sees it"
    assert sent[0]["status"] == 401
    challenge = dict(sent[0]["headers"])[b"www-authenticate"].decode()
    assert f'resource_metadata="{oauth.metadata_url()}"' in challenge
    assert ('error="invalid_token"' in challenge) is invalid


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_realm_token_for_this_server_reads_as_its_person(signed_in):
    principal = await authenticate(fake_request(f"Bearer {_token()}"), attempted_action="tools/list")

    assert principal.user == signed_in
    assert principal.credential_kind == "oauth"
    assert principal.workspace is None, "the person's workspace is resolved per call"
    assert not (registry.permitted_by(principal.scopes) & {s.name for s in registry.all_specs().values() if s.writes})


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_an_oauth_session_reads_the_workspace(signed_in, mcp_owner):
    _, bound, _ = mcp_owner

    async with mcp_http() as client:
        response = await call(client, "tools/call", token=_token(), name="get_workspace_summary", arguments={})

    result = parse(response)["result"]
    assert result.get("isError") is not True, result
    assert result["structuredContent"]["workspace"]["name"] == bound.name


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: _token(aud="sbomify"), id="issued to the web app"),
        pytest.param(lambda: _token(exp=int(time.time()) - 60), id="expired"),
        pytest.param(lambda: _token(sub="kc-never-signed-in"), id="nobody in sbomify"),
        pytest.param(lambda: _token(scope="openid email"), id="without the mcp scope"),
        pytest.param(lambda: _token(kid="made-up"), id="signed with a key the realm lacks"),
    ],
)
async def test_a_realm_token_not_meant_for_this_server_is_refused(signed_in, token):
    with pytest.raises(MCPAuthError, match="Invalid or expired"):
        await authenticate(fake_request(f"Bearer {token()}"), attempted_action="tools/list")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_deactivated_person_is_refused(signed_in):
    signed_in.is_active = False
    await sync_to_async(signed_in.save)()

    with pytest.raises(MCPAuthError, match="Invalid or expired"):
        await authenticate(fake_request(f"Bearer {_token()}"), attempted_action="tools/list")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_soft_deleted_person_is_refused(signed_in):
    from django.utils import timezone

    signed_in.deleted_at = timezone.now()
    await sync_to_async(signed_in.save)()

    with pytest.raises(MCPAuthError, match="Invalid or expired"):
        await authenticate(fake_request(f"Bearer {_token()}"), attempted_action="tools/list")


def test_made_up_key_ids_force_one_fetch_a_window(realm_keys):
    """Without the window, every token naming an unknown key would cost a fetch from Keycloak."""
    for n in range(5):
        assert oauth.verify(_token(kid=f"made-up-{n}")) is None

    assert realm_keys.forced_fetches == 1


def test_a_schemeless_base_url_still_names_an_absolute_resource(settings):
    settings.APP_BASE_URL = "app.example.com/"

    assert oauth.resource() == "https://app.example.com/mcp"
    assert oauth.metadata_url() == "https://app.example.com/.well-known/oauth-protected-resource/mcp"

