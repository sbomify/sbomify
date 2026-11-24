"""The authorize URL must not depend on ``+`` meaning a space.

Keycloak rejected a minority of logins with ``Invalid scopes:
openid+email+profile``: the separators reached it escaped, so all three
scopes arrived as one token and the user landed back on the login page.
The value is correct when it leaves us, which is why most logins work, so
these pin the property that removes the ambiguity rather than the hop that
exploits it.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlparse

from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from allauth.socialaccount.providers.openid_connect.views import OpenIDConnectOAuth2Adapter

from sbomify.apps.core.adapters import SpaceEncodedOAuth2Client

AUTHORIZE = "https://kc.example.test/realms/sbomify/protocol/openid-connect/auth"
SCOPE = ["openid", "email", "profile"]


def _client(cls: type) -> Any:
    return cls(
        None,
        "sbomify",
        "secret",
        "POST",
        "https://kc.example.test/realms/sbomify/protocol/openid-connect/token",
        "https://app.example.test/accounts/oidc/keycloak/login/callback/",
    )


def _query(url: str) -> dict[str, str]:
    return dict(parse_qsl(urlparse(url).query, keep_blank_values=True))


class TestScopeSeparatorsSurviveAReEncode:
    def test_the_separator_is_percent_encoded(self) -> None:
        url = _client(SpaceEncodedOAuth2Client).get_redirect_url(AUTHORIZE, SCOPE, {})

        query = urlparse(url).query
        assert "%20" in query
        # A bare + is the ambiguity: a reader following RFC 3986 sees a
        # literal character and re-encodes it to %2B, which is the failure.
        assert "+" not in query
        assert set(_query(url)["scope"].split()) == set(SCOPE)

    def test_the_scopes_still_arrive_as_three(self) -> None:
        """What a strict reader and a form reader each make of the value."""
        url = _client(SpaceEncodedOAuth2Client).get_redirect_url(AUTHORIZE, SCOPE, {})
        raw = _query(url)["scope"]

        assert len(raw.split()) == 3
        assert "+" not in raw

    def test_nothing_else_about_the_url_moves(self) -> None:
        extra = {"prompt": "login", "code_challenge_method": "S256"}
        ours = _client(SpaceEncodedOAuth2Client).get_redirect_url(AUTHORIZE, SCOPE, extra)
        theirs = _client(OAuth2Client).get_redirect_url(AUTHORIZE, SCOPE, extra)

        assert urlparse(ours)._replace(query="") == urlparse(theirs)._replace(query="")
        ours_params, theirs_params = _query(ours), _query(theirs)
        # Scope order comes from a set, so compare it as one.
        assert set(ours_params.pop("scope").split()) == set(theirs_params.pop("scope").split())
        assert ours_params == theirs_params

    def test_a_literal_plus_is_still_a_plus(self) -> None:
        """A PKCE challenge is base64 and can carry a real +."""
        url = _client(SpaceEncodedOAuth2Client).get_redirect_url(
            AUTHORIZE, SCOPE, {"code_challenge": "E9Melhoa2Ow_iaL3Ph1O+Cg"}
        )

        assert _query(url)["code_challenge"] == "E9Melhoa2Ow_iaL3Ph1O+Cg"

    def test_the_keycloak_provider_uses_this_client(self) -> None:
        assert OpenIDConnectOAuth2Adapter.client_class is SpaceEncodedOAuth2Client
