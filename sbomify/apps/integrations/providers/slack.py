"""Slack: the spec for the connection, and a thin client over the two calls it needs.

Slack is the first provider sbomify writes to rather than reads from. The
workspace installs the sbomify app through Slack's OAuth v2 flow, which hands
back one bot token for that Slack workspace, and the settings tab then picks a
channel for each kind of news (``NotificationRoute``).

Three things Slack does differently from Vanta, all carried on the spec rather
than branched on in the shared OAuth code:

- the token endpoint takes form encoding and refuses JSON;
- the bot token never expires, and arrives with no refresh token;
- every API call answers 200, and a failure is ``{"ok": false, "error": ...}``
  in the body. So a response is never trusted on its status alone.

``chat:write.public`` is what lets the bot post to a public channel without
being invited first. A private channel lists only once the app is a member of
it, which is Slack's rule and the reason the tab says to invite it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings

from sbomify.apps.core.domain.exceptions import ExternalServiceError
from sbomify.apps.core.integrations.http import request_with_retry
from sbomify.apps.integrations.exceptions import ProviderAuthError, ProviderUnavailable
from sbomify.apps.integrations.providers.base import ProviderSpec
from sbomify.logging import getLogger

logger = getLogger(__name__)

SLACK = ProviderSpec(
    key="slack",
    name="Slack",
    tagline="Send the VEX approval queue and vulnerability news to your Slack channels.",
    icon="fab fa-slack",
    docs_url="https://api.slack.com/authentication/oauth-v2",
    reads_intro="Once connected, sbomify can:",
    reads=(
        "See the names of your channels, so you can pick where each message goes",
        "Post messages to the channels you pick, and nowhere else",
    ),
    scopes=("chat:write", "chat:write.public", "channels:read", "groups:read"),
    authorize_url_setting="SLACK_OAUTH_AUTHORIZE_URL",
    exchange_url_setting="SLACK_OAUTH_TOKEN_URL",
    client_id_setting="SLACK_CLIENT_ID",
    client_credential_setting="SLACK_CLIENT_SECRET",
    kind="notifications",
    exchange_encoding="form",
    scope_separator=",",
    tokens_expire=False,
    account_path="sbomify.apps.integrations.providers.slack.account",
)

# Slack's own ceiling for conversations.list is 1000; it recommends 200 and
# throttles larger pages harder.
PAGE_SIZE = 200

# Ten pages is two thousand channels. A guard against a cursor that never
# ends, not a Slack limit.
MAX_PAGES = 10

# Errors that mean the token is no good any more. Nothing posts again until
# somebody reconnects, so the connection is marked as needing it.
AUTH_ERRORS = frozenset(
    {
        "account_inactive",
        "invalid_auth",
        "missing_scope",
        "not_allowed_token_type",
        "not_authed",
        "token_expired",
        "token_revoked",
    }
)

# Errors about the one channel, not the connection. The route records them and
# every other route keeps working.
CHANNEL_ERRORS = frozenset(
    {
        "channel_not_found",
        "is_archived",
        "not_in_channel",
        "restricted_action",
        "restricted_action_non_threadable_channel",
        "restricted_action_read_only_channel",
        "restricted_action_thread_only_channel",
    }
)

CHANNEL_ERROR_MESSAGES = {
    "channel_not_found": "That channel no longer exists, or sbomify cannot see it.",
    "is_archived": "That channel is archived.",
    "not_in_channel": "Invite the sbomify app to that channel, then try again.",
}


class SlackChannelError(ExternalServiceError):
    """Slack refused one channel. The route needs a different one."""

    error_code = "slack_channel_error"


@dataclass(frozen=True)
class Channel:
    id: str
    name: str
    is_private: bool


def account(data: dict[str, Any]) -> dict[str, str]:
    """The Slack workspace a token response belongs to."""
    team = data.get("team")
    if not isinstance(team, dict):
        return {}
    return {key: str(team[key]) for key in ("id", "name") if isinstance(team.get(key), str)}


def _base_url() -> str:
    return str(getattr(settings, "SLACK_API_BASE_URL", "") or "https://slack.com/api").rstrip("/")


class SlackClient:
    """The two Slack Web API calls sbomify makes, with Slack's errors sorted.

    Never logs a response body: an error echo can carry the token back.
    """

    def __init__(self, token: str) -> None:
        self._token = token

    def _call(self, method: str, api_method: str, **kwargs: Any) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        if "json" in kwargs:
            headers["Content-Type"] = "application/json; charset=utf-8"
        try:
            response = request_with_retry(method, f"{_base_url()}/{api_method}", headers=headers, **kwargs)
        except requests.RequestException as exc:
            raise ProviderUnavailable(f"Could not reach Slack: {exc}", service="slack") from exc

        if response.status_code == 429 or response.status_code >= 500:
            logger.warning("Slack %s returned %s", api_method, response.status_code)
            raise ProviderUnavailable("Slack is not answering.", service="slack")
        if response.status_code in (401, 403):
            raise ProviderAuthError("Slack refused the stored credential.", service="slack")

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderUnavailable("Slack returned an unreadable response.", service="slack") from exc
        if not isinstance(data, dict):
            raise ProviderUnavailable("Slack returned an unreadable response.", service="slack")

        if data.get("ok") is True:
            return data

        error = str(data.get("error") or "unknown_error")
        logger.warning("Slack %s failed: %s", api_method, error)
        if error in AUTH_ERRORS:
            raise ProviderAuthError("Slack refused the stored credential.", service="slack")
        if error in CHANNEL_ERRORS:
            raise SlackChannelError(
                CHANNEL_ERROR_MESSAGES.get(error, "Slack would not post to that channel."), service="slack"
            )
        if error == "ratelimited":
            raise ProviderUnavailable("Slack is not answering.", service="slack")
        raise ProviderUnavailable(f"Slack could not complete the request ({error}).", service="slack")

    def list_channels(self) -> list[Channel]:
        """Every unarchived channel the bot can post to, by name.

        Public channels are all listed. A private channel lists only once the
        app has been invited to it, which is also the only way it could post
        there.
        """
        channels: list[Channel] = []
        cursor = ""
        for _page in range(MAX_PAGES):
            params: dict[str, Any] = {
                "types": "public_channel,private_channel",
                "exclude_archived": "true",
                "limit": PAGE_SIZE,
            }
            if cursor:
                params["cursor"] = cursor
            data = self._call("GET", "conversations.list", params=params)
            for item in data.get("channels") or []:
                if not isinstance(item, dict):
                    continue
                channel_id, name = item.get("id"), item.get("name")
                if isinstance(channel_id, str) and channel_id and isinstance(name, str):
                    channels.append(Channel(id=channel_id, name=name, is_private=bool(item.get("is_private"))))
            metadata = data.get("response_metadata")
            cursor = metadata.get("next_cursor", "") if isinstance(metadata, dict) else ""
            if not cursor:
                break
        else:
            logger.warning("Slack channel list ran past %d pages; showing the first %d", MAX_PAGES, len(channels))
        return sorted(channels, key=lambda channel: channel.name.casefold())

    def post_message(self, channel_id: str, text: str, blocks: list[dict[str, Any]]) -> None:
        """Post one message. ``text`` is what notifications and screen readers get."""
        self._call(
            "POST",
            "chat.postMessage",
            json={"channel": channel_id, "text": text, "blocks": blocks, "unfurl_links": False},
        )
