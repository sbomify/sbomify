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

    A run still in flight is the exception. It is reading the credential this
    call has just replaced, so the reconnect ends it: the claim comes off, and
    the run the callback queues can take the connection straight away instead
    of waiting out a lease it would otherwise have just renewed.
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

    if integration.last_sync_status == Integration.SyncStatus.RUNNING:
        integration.last_sync_status = Integration.SyncStatus.FAILED
        integration.last_sync_error = "A reconnect replaced the credential this sync started with."
        integration.save(update_fields=["last_sync_status", "last_sync_error", "updated_at"])

    return integration


def access_token(integration: Integration, provider: ProviderSpec) -> str:
    """A usable access token, refreshing and persisting the rotation first.

    Vanta rotates the refresh token on every use, so the new one is saved
    before the access token is handed out: if the caller then dies mid-sync,
    the workspace is still connected.

    **The refresh is serialised on the row.** A provider that rotates its
    refresh token turns a concurrent refresh into a lost connection rather than
    a wasted request: two callers read the same token, both spend it, and the
    loser gets a 401 that reads as a dead credential and marks a perfectly good
    connection as needing a reconnect. "Sync now" landing on top of the
    scheduled run is exactly that race. Taking the row lock first means the
    second caller waits, then finds the token already fresh and never sends a
    request at all.

    Only a refusal is terminal. An unreachable provider raises
    ``ProviderUnavailable`` and leaves the connection alone, so the next
    scheduled sync can pick it up.
    """
    if not integration.token_is_stale:
        return integration.access_token

    # The marking of a dead credential is deliberately outside this block. A
    # ``_mark_revoked`` written inside it would be rolled back by the very
    # exception that caused it, and the connection would come out of a refusal
    # still looking healthy, so the refusal is carried out and applied after
    # the transaction closes.
    refusal: ProviderAuthError | None = None
    revoke_reason = ""

    with transaction.atomic():
        locked = Integration.objects.select_for_update().filter(pk=integration.pk).first()
        if locked is None:
            raise ProviderAuthError(f"{provider.name} is no longer connected.", service=provider.key)

        # Re-read under the lock. Whoever held it before us may already have
        # rotated, in which case there is nothing to do.
        if not locked.token_is_stale:
            _copy_credential(locked, integration)
            return locked.access_token

        if not locked.refresh_token:
            revoke_reason = "The connection has no refresh token. Reconnect the workspace."
            refusal = ProviderAuthError(f"{provider.name} needs reconnecting.", service=provider.key)
        else:
            try:
                token_set = oauth.refresh(provider, locked.refresh_token)
            except ProviderAuthError as exc:
                revoke_reason = f"{provider.name} rejected the stored credential."
                refusal = exc
            else:
                locked.access_token = token_set.access_token
                # An empty rotation means the provider reissued without
                # replacing; keeping the old refresh token is what lets the
                # next refresh work at all.
                locked.refresh_token = token_set.refresh_token or locked.refresh_token
                locked.token_expires_at = token_set.expires_at
                locked.scopes = list(token_set.scopes)
                locked.status = Integration.Status.CONNECTED
                locked.save(
                    update_fields=[
                        "access_token",
                        "refresh_token",
                        "token_expires_at",
                        "scopes",
                        "status",
                        "updated_at",
                    ]
                )

    if refusal is not None:
        _mark_revoked(locked, revoke_reason)
        _copy_credential(locked, integration)
        raise refusal

    _copy_credential(locked, integration)
    return locked.access_token


def _copy_credential(source: Integration, target: Integration) -> None:
    """Bring the caller's in-memory row up to date with the locked copy.

    The caller holds the instance it passed in and goes on using it after this
    returns, so it has to see whatever the locked row decided.
    """
    target.access_token = source.access_token
    target.refresh_token = source.refresh_token
    target.token_expires_at = source.token_expires_at
    target.scopes = source.scopes
    target.status = source.status
    target.last_sync_status = source.last_sync_status
    target.last_sync_error = source.last_sync_error


def _mark_revoked(integration: Integration, message: str) -> None:
    """Flag a dead credential, unless one has already replaced it.

    This runs after the lock is gone, so a reconnect can land in between, and
    saving the instance we hold would push a stale refusal over a working
    connection. The refresh token we were refused on is what the write is keyed
    to: if the row still carries it, the refusal is still true about what is
    stored; if it does not, somebody has reconnected and being asked to
    reconnect again is wrong.
    """
    replaced = Integration.objects.filter(pk=integration.pk, refresh_token=integration.refresh_token).update(
        status=Integration.Status.REVOKED,
        last_sync_status=Integration.SyncStatus.FAILED,
        last_sync_error=message,
        updated_at=timezone.now(),
    )
    if replaced:
        integration.status = Integration.Status.REVOKED
        integration.last_sync_status = Integration.SyncStatus.FAILED
        integration.last_sync_error = message
        return

    # Somebody reconnected while we were being refused. This call still failed,
    # so the caller still gets its error, but the row now describes the new
    # credential and the instance has to say so too.
    current = Integration.objects.filter(pk=integration.pk).first()
    if current is not None:
        _copy_credential(current, integration)


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
        ControlCatalog.objects.filter(team=team, source=provider_key, is_published=True).update(
            is_published=False, updated_at=timezone.now()
        )
        integration.delete()

    logger.info("Disconnected %s for workspace %s", provider_key, team.key)
    return ServiceResult.success(None)


def provider_cards(team: Team) -> list[dict[str, Any]]:
    """One entry per registered provider, for the Integrations tab.

    Tokens never appear, and not because the template happens not to render
    them: what goes in the context is a mapping of the sync fields the panel
    reads, so a field added to ``Integration`` later cannot arrive on a page by
    being added to the model.
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
                "integration": _sync_state(integration),
                "is_connected": integration is not None,
                "needs_reconnect": integration is not None and integration.status == Integration.Status.REVOKED,
                "catalogs": [
                    {
                        "id": catalog.id,
                        "name": catalog.name,
                        "version": catalog.version,
                        "is_published": catalog.is_published,
                        "control_count": catalog.control_count,
                    }
                    for catalog in catalogs
                ],
            }
        )
    return cards


def _sync_state(integration: Integration | None) -> dict[str, Any] | None:
    """What the Integrations tab says about a connection, and nothing else."""
    if integration is None:
        return None
    return {
        "last_sync_at": integration.last_sync_at,
        "last_sync_status": integration.last_sync_status,
        "last_sync_error": integration.last_sync_error,
        "connected_by": integration.connected_by,
    }


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
    if not catalog.is_integration_owned:
        return ServiceResult.failure("That framework is not managed by an integration", status_code=400)

    if catalog.is_published != published:
        catalog.is_published = published
        catalog.save(update_fields=["is_published", "updated_at"])

    return ServiceResult.success(catalog.name)
