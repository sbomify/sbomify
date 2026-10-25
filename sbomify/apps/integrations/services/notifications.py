"""Where a notification connection sends each kind of news, and the sending.

A notification provider (Slack) is written to rather than read from, so where
a compliance connection has frameworks it has routes: one
``NotificationRoute`` per event, naming the channel that event goes to.

Views call into here for the settings tab; the tasks call ``deliver``. Nothing
here knows about HTTP responses, and nothing raises to a view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.core.cache import cache
from django.db.models import QuerySet
from django.utils import timezone

from sbomify.apps.core.domain.exceptions import ExternalServiceError
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.integrations.exceptions import ProviderAuthError, ProviderUnavailable
from sbomify.apps.integrations.models import Integration, NotificationRoute
from sbomify.apps.integrations.providers import get_provider
from sbomify.apps.integrations.providers.slack import Channel, SlackChannelError, SlackClient
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.integrations.services.messages import Message
    from sbomify.apps.teams.models import Workspace

logger = getLogger(__name__)

# Long enough that the panel re-rendering after every change does not list the
# channels again each time, short enough that a channel created a minute ago
# is there when somebody goes looking for it.
CHANNEL_CACHE_SECONDS = 300


@dataclass(frozen=True)
class EventSpec:
    key: str
    label: str
    description: str
    has_severity: bool = False


EVENTS: tuple[EventSpec, ...] = (
    EventSpec(
        key=NotificationRoute.Event.VEX_SUBMISSIONS,
        label="VEX approval queue",
        description="A message each time a VEX ruling is waiting for approval.",
    ),
    EventSpec(
        key=NotificationRoute.Event.DAILY_DIGEST,
        label="Daily vulnerability digest",
        description="Open vulnerabilities across the workspace, every day at 08:00 UTC.",
    ),
    EventSpec(
        key=NotificationRoute.Event.NEW_VULNERABILITIES,
        label="New vulnerabilities",
        description="A message when a scan finds a vulnerability a component did not have before.",
        has_severity=True,
    ),
)

EVENTS_BY_KEY: dict[str, EventSpec] = {event.key: event for event in EVENTS}


def _client(integration: Integration) -> SlackClient:
    from sbomify.apps.integrations.services.connections import access_token

    provider = get_provider(integration.provider)
    if provider is None or provider.kind != "notifications":
        raise ProviderUnavailable("This connection does not send notifications.", service=integration.provider)
    return SlackClient(access_token(integration, provider))


def _cache_key(integration: Integration) -> str:
    # The generation is in the key, so a reconnect to another Slack workspace
    # never offers the old workspace's channels.
    return f"integrations:channels:{integration.id}:{integration.connected_at.timestamp()}"


def list_channels(integration: Integration) -> ServiceResult[list[Channel]]:
    """The channels this connection can post to, cached for a few minutes."""
    cached = cache.get(_cache_key(integration))
    if isinstance(cached, list):
        return ServiceResult.success([Channel(**item) for item in cached])

    try:
        channels = _client(integration).list_channels()
    except ProviderAuthError as exc:
        mark_revoked(integration, exc.detail)
        return ServiceResult.failure(exc.detail, status_code=exc.status_code)
    except ExternalServiceError as exc:
        return ServiceResult.failure(exc.detail, status_code=exc.status_code)

    cache.set(
        _cache_key(integration),
        [{"id": channel.id, "name": channel.name, "is_private": channel.is_private} for channel in channels],
        CHANNEL_CACHE_SECONDS,
    )
    return ServiceResult.success(channels)


def routes_panel(integration: Integration) -> dict[str, Any]:
    """What the Integrations tab shows under a connected notification provider.

    The channel list is read only while the connection works: a revoked token
    would only be refused again, and the tab already says to reconnect.
    """
    routes = {route.event: route for route in integration.routes.all()}

    channels: list[Channel] = []
    channels_error = ""
    if integration.status == Integration.Status.CONNECTED:
        result = list_channels(integration)
        if result.ok and result.value is not None:
            channels = result.value
        else:
            channels_error = result.error or "Could not list your channels."

    channel_options = [
        {"value": channel.id, "label": f"#{channel.name}{' (private)' if channel.is_private else ''}"}
        for channel in channels
    ]
    known = {channel.id for channel in channels}

    events = []
    for event in EVENTS:
        route = routes.get(event.key)
        options = list(channel_options)
        # A routed channel the list no longer shows (archived, or the app was
        # removed from it) stays selectable as itself, so the select does not
        # claim the event is going somewhere else.
        if route is not None and route.channel_id not in known:
            options.insert(0, {"value": route.channel_id, "label": f"#{route.channel_name or route.channel_id}"})
        events.append(
            {
                "key": event.key,
                "label": event.label,
                "description": event.description,
                "has_severity": event.has_severity,
                # Nothing to pick from and nothing picked: Slack could not be
                # read, and an enabled select would only offer "Off".
                "select_disabled": not channels and route is None,
                "channel_options": [{"value": "", "label": "Off"}, *options],
                "severity_options": [
                    {"value": value, "label": label} for value, label in NotificationRoute.Severity.choices
                ],
                "route": (
                    {
                        "channel_id": route.channel_id,
                        "channel_name": route.channel_name,
                        "min_severity": route.min_severity,
                        "last_delivered_at": route.last_delivered_at,
                        "last_error": route.last_error,
                    }
                    if route is not None
                    else None
                ),
            }
        )

    return {"events": events, "channels_error": channels_error, "has_channels": bool(channels)}


def _notification_integration(team: Workspace, provider_key: str) -> Integration | None:
    provider = get_provider(provider_key)
    if provider is None or provider.kind != "notifications":
        return None
    return Integration.objects.filter(team=team, provider=provider.key).first()


def set_route(
    team: Workspace, provider_key: str, event: str, channel_id: str, min_severity: str = ""
) -> ServiceResult[str]:
    """Send ``event`` to ``channel_id``, or stop sending it when the id is empty.

    The channel must be one the connection can list, so a hand-edited form
    cannot point a workspace's news at a channel id it typed.
    """
    integration = _notification_integration(team, provider_key)
    if integration is None:
        return ServiceResult.failure("Not connected", status_code=404)
    spec = EVENTS_BY_KEY.get(event)
    if spec is None:
        return ServiceResult.failure("Unknown notification", status_code=400)

    channel_id = (channel_id or "").strip()
    if not channel_id:
        NotificationRoute.objects.filter(integration=integration, event=spec.key).delete()
        return ServiceResult.success(f"{spec.label} is off.")

    if integration.status != Integration.Status.CONNECTED:
        return ServiceResult.failure("Reconnect Slack before choosing a channel", status_code=409)

    existing = NotificationRoute.objects.filter(integration=integration, event=spec.key).first()
    if existing is not None and existing.channel_id == channel_id:
        channel_name = existing.channel_name
    else:
        listed = list_channels(integration)
        if not listed.ok or listed.value is None:
            return ServiceResult.failure(listed.error or "Could not list your channels", status_code=502)
        channel = next((item for item in listed.value if item.id == channel_id), None)
        if channel is None:
            return ServiceResult.failure("That channel is not one sbomify can post to", status_code=400)
        channel_name = channel.name

    defaults: dict[str, Any] = {"channel_id": channel_id, "channel_name": channel_name}
    if spec.has_severity and min_severity:
        if min_severity not in NotificationRoute.Severity.values:
            return ServiceResult.failure("Unknown severity", status_code=400)
        defaults["min_severity"] = min_severity
    if existing is None or existing.channel_id != channel_id:
        # A new channel starts with a clean record: the last error was about
        # the channel it replaces.
        defaults["last_error"] = ""

    NotificationRoute.objects.update_or_create(integration=integration, event=spec.key, defaults=defaults)
    return ServiceResult.success(f"{spec.label} goes to #{channel_name}.")


def send_test(team: Workspace, provider_key: str, event: str) -> ServiceResult[str]:
    """Post a test message to the channel ``event`` is routed to, now."""
    from sbomify.apps.integrations.services.messages import connection_test_message

    integration = _notification_integration(team, provider_key)
    if integration is None:
        return ServiceResult.failure("Not connected", status_code=404)
    spec = EVENTS_BY_KEY.get(event)
    if spec is None:
        return ServiceResult.failure("Unknown notification", status_code=400)
    route = NotificationRoute.objects.filter(integration=integration, event=spec.key).first()
    if route is None:
        return ServiceResult.failure(f"Pick a channel for {spec.label} first", status_code=400)

    result = deliver(route, connection_test_message(team, spec.label))
    if not result.ok:
        return ServiceResult.failure(result.error or "Could not post the test message", status_code=502)
    return ServiceResult.success(f"Sent a test message to #{route.channel_name or route.channel_id}.")


def active_routes(team_id: Any, event: str) -> QuerySet[NotificationRoute]:
    """The routes ``event`` goes out on for a workspace, over working connections only."""
    return NotificationRoute.objects.filter(
        integration__team_id=team_id,
        integration__status=Integration.Status.CONNECTED,
        event=event,
    ).select_related("integration", "integration__team")


def deliver(route: NotificationRoute, message: Message) -> ServiceResult[None]:
    """Post one message on one route and record how it went on the route.

    Only an unreachable Slack raises, as ``ProviderUnavailable``, so the task
    that called this can retry it. A refused token marks the connection as
    needing a reconnect, and a refused channel is recorded on the route; no
    retry can fix either.
    """
    integration = route.integration
    try:
        _client(integration).post_message(route.channel_id, message.text, message.blocks)
    except ProviderAuthError as exc:
        mark_revoked(integration, exc.detail)
        _record(route, last_error=exc.detail)
        return ServiceResult.failure(exc.detail, status_code=exc.status_code)
    except SlackChannelError as exc:
        _record(route, last_error=exc.detail)
        return ServiceResult.failure(exc.detail, status_code=exc.status_code)
    except ProviderUnavailable as exc:
        _record(route, last_error=exc.detail)
        raise

    _record(route, last_delivered_at=timezone.now(), last_error="")
    return ServiceResult.success(None)


def _record(route: NotificationRoute, **fields: Any) -> None:
    for field, value in fields.items():
        setattr(route, field, value)
    NotificationRoute.objects.filter(pk=route.pk).update(updated_at=timezone.now(), **fields)


def mark_revoked(integration: Integration, message: str) -> None:
    """Flag a refused token, unless a reconnect has replaced it meanwhile.

    Keyed to ``connected_at`` like every other write after a provider call: a
    reconnect moves it, and the refusal is about the credential it replaced.
    """
    Integration.objects.filter(pk=integration.pk, connected_at=integration.connected_at).update(
        status=Integration.Status.REVOKED,
        last_sync_error=message,
        updated_at=timezone.now(),
    )
    integration.status = Integration.Status.REVOKED
    integration.last_sync_error = message
