"""Connect, disconnect, and keep a connection's credential usable.

Views call into here; nothing in this module knows about HTTP responses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.integrations import oauth
from sbomify.apps.integrations.exceptions import ProviderAuthError
from sbomify.apps.integrations.models import Integration
from sbomify.apps.integrations.providers import PROVIDERS, ProviderSpec
from sbomify.logging import getLogger

if TYPE_CHECKING:
    from sbomify.apps.core.models import User
    from sbomify.apps.teams.models import Team

logger = getLogger(__name__)


def get_integration(team: Team, provider_key: str) -> Integration | None:
    """This workspace's connection to ``provider_key``, if it has one."""
    return Integration.objects.filter(team=team, provider=provider_key).first()


def save_connection(
    team: Team,
    provider: ProviderSpec,
    token_set: oauth.TokenSet,
    user: User | None,
) -> Integration:
    """Store a freshly authorized connection, replacing any earlier one.

    Reconnecting is an update rather than a second row: a workspace has one
    connection per provider, and the sync state from the previous credential
    is still true about the data on the trust center.
    """
    integration, _created = Integration.objects.update_or_create(
        team=team,
        provider=provider.key,
        defaults={
            "status": Integration.Status.CONNECTED,
            "access_token": token_set.access_token,
            "refresh_token": token_set.refresh_token,
            "token_expires_at": token_set.expires_at,
            "scopes": list(token_set.scopes),
            "connected_by": user,
            "connected_at": timezone.now(),
        },
    )
    return integration


def access_token(integration: Integration, provider: ProviderSpec) -> str:
    """A usable access token, refreshing and persisting the rotation first.

    Vanta rotates the refresh token on every use, so the new one is saved
    before the access token is handed out: if the caller then dies mid-sync,
    the workspace is still connected.

    A refusal here is terminal. The connection is marked so the settings page
    can ask for a reconnect instead of retrying forever against a credential
    the provider has forgotten.
    """
    if not integration.token_is_stale:
        return integration.access_token

    if not integration.refresh_token:
        _mark_revoked(integration, "The connection has no refresh token. Reconnect the workspace.")
        raise ProviderAuthError(f"{provider.name} needs reconnecting.", service=provider.key)

    try:
        token_set = oauth.refresh(provider, integration.refresh_token)
    except ProviderAuthError:
        _mark_revoked(integration, f"{provider.name} rejected the stored credential.")
        raise

    integration.access_token = token_set.access_token
    # An empty rotation means the provider reissued without replacing; keeping
    # the old refresh token is what lets the next refresh work at all.
    integration.refresh_token = token_set.refresh_token or integration.refresh_token
    integration.token_expires_at = token_set.expires_at
    integration.scopes = list(token_set.scopes)
    integration.status = Integration.Status.CONNECTED
    integration.save(
        update_fields=["access_token", "refresh_token", "token_expires_at", "scopes", "status", "updated_at"]
    )
    return integration.access_token


def _mark_revoked(integration: Integration, message: str) -> None:
    integration.status = Integration.Status.REVOKED
    integration.last_sync_status = Integration.SyncStatus.FAILED
    integration.last_sync_error = message
    integration.save(update_fields=["status", "last_sync_status", "last_sync_error", "updated_at"])


def disconnect(team: Team, provider_key: str) -> ServiceResult[None]:
    """Drop the connection and take everything it published off the trust center.

    The synced frameworks and their controls are kept but unpublished. Keeping
    them means a reconnect is not a re-import; unpublishing them means a public
    page never goes on claiming a control is met from a source nobody is
    reading any more.
    """
    integration = get_integration(team, provider_key)
    if integration is None:
        return ServiceResult.failure("Not connected", status_code=404)

    from sbomify.apps.controls.models import ControlCatalog

    with transaction.atomic():
        ControlCatalog.objects.filter(team=team, source=provider_key, is_active=True).update(
            is_active=False, updated_at=timezone.now()
        )
        integration.delete()

    logger.info("Disconnected %s for workspace %s", provider_key, team.key)
    return ServiceResult.success(None)


def provider_cards(team: Team) -> list[dict[str, Any]]:
    """One entry per registered provider, for the Integrations tab.

    Tokens never appear. ``redacted_token`` is the only credential-shaped
    thing that reaches a template.
    """
    connections = {integration.provider: integration for integration in Integration.objects.filter(team=team)}

    from sbomify.apps.controls.models import ControlCatalog

    cards: list[dict[str, Any]] = []
    for provider in PROVIDERS:
        integration = connections.get(provider.key)
        catalogs = (
            list(
                ControlCatalog.objects.filter(team=team, source=provider.key)
                .annotate(control_count=Count("controls"))
                .order_by("name")
            )
            if integration is not None
            else []
        )
        cards.append(
            {
                "provider": provider,
                "integration": integration,
                "is_connected": integration is not None,
                "needs_reconnect": integration is not None and integration.status == Integration.Status.REVOKED,
                "catalogs": [
                    {
                        "id": catalog.id,
                        "name": catalog.name,
                        "version": catalog.version,
                        "is_active": catalog.is_active,
                        "control_count": catalog.control_count,
                    }
                    for catalog in catalogs
                ],
            }
        )
    return cards


def set_catalog_published(team: Team, catalog_id: str, published: bool) -> ServiceResult[str]:
    """Show or hide one synced framework on the trust center.

    Publishing is a separate, deliberate act from connecting, for the same
    reason ``product:set_visibility`` is not part of ``MANAGE``: connecting
    reads data, publishing puts a claim on a page the workspace's customers
    read. A first sync therefore lands unpublished and someone chooses.
    """
    from sbomify.apps.controls.models import ControlCatalog

    catalog = ControlCatalog.objects.filter(id=catalog_id, team=team).first()
    if catalog is None:
        return ServiceResult.failure("Framework not found", status_code=404)
    if catalog.source not in {provider.key for provider in PROVIDERS}:
        return ServiceResult.failure("That framework is not managed by an integration", status_code=400)

    if catalog.is_active != published:
        catalog.is_active = published
        catalog.save(update_fields=["is_active", "updated_at"])

    return ServiceResult.success(catalog.name)
