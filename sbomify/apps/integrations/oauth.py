"""The authorization-code flow, with nothing provider-specific in it.

Two things here are worth knowing before editing:

**The redirect URI is fixed per provider and carries no workspace.** Providers
register one exact callback URL and refuse anything else, so the workspace
being connected cannot travel in the path. It travels in the session instead,
alongside the ``state`` nonce, which is also what makes the flow safe: the
callback is only accepted in the browser that started it.

**State lives in the session, not in a signature.** A signed state would be
replayable in any browser until it expired; a session-held nonce is not.
``consume_state`` deletes it on the way past, so the callback is single-use
whether it succeeded or failed.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.core.integrations.http import request_with_retry
from sbomify.apps.integrations.exceptions import ProviderAuthError, ProviderUnavailable
from sbomify.apps.integrations.providers.base import ProviderSpec
from sbomify.logging import getLogger

logger = getLogger(__name__)

SESSION_KEY = "integrations_oauth_flow"

# Long enough for a consent screen that needs a sign-in and an MFA prompt,
# short enough that an abandoned flow does not sit in the session all day.
STATE_MAX_AGE = timedelta(minutes=15)


@dataclass(frozen=True)
class TokenSet:
    """What a token endpoint hands back, in the shape the model stores."""

    access_token: str
    refresh_token: str
    expires_at: datetime | None
    scopes: tuple[str, ...]


def callback_url(request: HttpRequest, provider: ProviderSpec) -> str:
    """The absolute callback URL, which must match the provider's registration.

    Built from the request rather than from ``APP_BASE_URL`` so a deployment
    serving more than one hostname still sends the user back to the one they
    are on. Whatever this returns is the string to register with the provider.
    """
    return request.build_absolute_uri(reverse("integrations:callback", kwargs={"provider": provider.key}))


def start_authorization(request: HttpRequest, provider: ProviderSpec, team_key: str) -> str:
    """Record the pending flow on the session and return where to send the user."""
    nonce = secrets.token_urlsafe(32)
    request.session[SESSION_KEY] = {
        "provider": provider.key,
        "team_key": team_key,
        "nonce": nonce,
        "started_at": timezone.now().isoformat(),
    }
    # The session is mutated in place, so Django is told explicitly rather
    # than left to notice.
    request.session.modified = True

    params = {
        "client_id": provider.client_id,
        "redirect_uri": callback_url(request, provider),
        "response_type": "code",
        "scope": " ".join(provider.scopes),
        "state": nonce,
    }
    return f"{provider.authorize_url}?{urlencode(params)}"


def consume_state(request: HttpRequest, provider: ProviderSpec, state: str) -> str | None:
    """The workspace key this callback belongs to, or None if it does not.

    Always clears the pending flow, including on every rejection: a nonce that
    failed one check must not be available for a second attempt.
    """
    pending = request.session.pop(SESSION_KEY, None)
    request.session.modified = True

    if not isinstance(pending, dict):
        return None
    if pending.get("provider") != provider.key:
        return None

    nonce = pending.get("nonce")
    if not isinstance(nonce, str) or not state or not secrets.compare_digest(nonce, state):
        return None

    started_at = pending.get("started_at")
    if not isinstance(started_at, str):
        return None
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return None
    if timezone.now() - started > STATE_MAX_AGE:
        return None

    team_key = pending.get("team_key")
    return team_key if isinstance(team_key, str) and team_key else None


def exchange_code(request: HttpRequest, provider: ProviderSpec, code: str) -> TokenSet:
    """Trade an authorization code for a token set."""
    return _token_request(
        provider,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": callback_url(request, provider),
        },
    )


def refresh(provider: ProviderSpec, refresh_token: str) -> TokenSet:
    """Rotate an expiring token set. The result replaces both tokens."""
    return _token_request(
        provider,
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )


def _token_request(provider: ProviderSpec, payload: dict[str, str]) -> TokenSet:
    body = {
        "client_id": provider.client_id,
        "client_secret": provider.client_secret,
        **payload,
    }

    try:
        # JSON, not form encoding: Vanta's token endpoint rejects
        # ``application/x-www-form-urlencoded`` outright, and every provider
        # accepts JSON.
        response = request_with_retry(
            "POST",
            provider.token_url,
            json=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
    except requests.RequestException as exc:
        # A timeout or a DNS blip says nothing about the credential, so it must
        # not cost the workspace its connection.
        raise ProviderUnavailable(f"Could not reach {provider.name}: {exc}", service=provider.key) from exc

    if response.status_code >= 400:
        # The body can hold the client secret back in an error echo, so only
        # the status is logged and only a fixed string is shown.
        logger.warning("%s token endpoint returned %s", provider.key, response.status_code)
        if response.status_code >= 500:
            raise ProviderUnavailable(f"{provider.name} is not answering.", service=provider.key)
        # A 4xx is the provider answering, and for a grant that means the grant
        # itself was refused (``invalid_grant`` and friends are all 400).
        raise ProviderAuthError(f"{provider.name} refused the connection.", service=provider.key)

    try:
        data = response.json()
    except ValueError as exc:
        raise ProviderUnavailable(
            f"{provider.name} returned an unreadable token response.", service=provider.key
        ) from exc

    return _token_set(provider, data)


def _token_set(provider: ProviderSpec, data: Any) -> TokenSet:
    if not isinstance(data, dict):
        raise ProviderUnavailable(f"{provider.name} returned an unreadable token response.", service=provider.key)

    access_token = data.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ProviderUnavailable(f"{provider.name} returned no access token.", service=provider.key)

    refresh_token = data.get("refresh_token")
    refresh_token = refresh_token if isinstance(refresh_token, str) else ""

    expires_at: datetime | None = None
    expires_in = data.get("expires_in")
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        expires_at = timezone.now() + timedelta(seconds=int(expires_in))

    scope = data.get("scope")
    scopes = tuple(scope.split()) if isinstance(scope, str) and scope else provider.scopes

    return TokenSet(access_token=access_token, refresh_token=refresh_token, expires_at=expires_at, scopes=scopes)
