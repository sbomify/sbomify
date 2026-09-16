"""Run a provider's sync and record what happened to it.

The provider-specific work is behind ``ProviderSpec.sync_path``; everything
here is the bookkeeping every provider needs and none of them should repeat:
mark the run, catch the two failure shapes, and leave the connection in a
state the settings page can explain.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from django.utils.module_loading import import_string

from sbomify.apps.core.domain.exceptions import ExternalServiceError
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.integrations.exceptions import ProviderAuthError
from sbomify.apps.integrations.models import Integration
from sbomify.apps.integrations.providers import get_provider
from sbomify.logging import getLogger

logger = getLogger(__name__)


def run_sync(integration: Integration) -> ServiceResult[dict[str, Any]]:
    """Sync one connection, start to finish, and never raise.

    A sync is a background job reading someone else's API, so every way it can
    go wrong ends as a recorded failure rather than an exception: the caller is
    a task or a button, and neither has anywhere useful to put a traceback.
    """
    provider = get_provider(integration.provider)
    if provider is None:
        return ServiceResult.failure(f"Unknown provider: {integration.provider}", status_code=400)

    # Keyed to the generation like every other write here. `_claim` has already
    # set RUNNING for the task path; this is for a direct caller. Unconditional
    # it was a way to undo a reconnect: `save_connection` clears the claim so
    # the queued replacement can take it, and a stale worker writing RUNNING
    # through its old instance would block that replacement for the lease, or
    # later overwrite the newer run's OK.
    _record(integration, last_sync_status=Integration.SyncStatus.RUNNING)

    try:
        result: ServiceResult[dict[str, Any]] = import_string(provider.sync_path)(integration)
    except ProviderAuthError as exc:
        # ``connections.access_token`` has already flipped the connection to
        # "needs reconnecting"; this records why, in the same words the tab
        # shows.
        _record_failure(integration, exc.detail)
        return ServiceResult.failure(exc.detail, status_code=exc.status_code)
    except ExternalServiceError as exc:
        _record_failure(integration, exc.detail)
        return ServiceResult.failure(exc.detail, status_code=exc.status_code)
    except Exception:  # noqa: BLE001 - a broken sync must not poison the task queue
        logger.exception("Sync failed for %s on workspace %s", integration.provider, integration.team_id)
        message = f"{provider.name} sync failed unexpectedly."
        _record_failure(integration, message)
        return ServiceResult.failure(message, status_code=500)

    if not result.ok:
        _record_failure(integration, result.error or "Sync failed")
        return result

    _record(
        integration,
        last_sync_status=Integration.SyncStatus.OK,
        last_sync_at=timezone.now(),
        last_sync_error="",
        last_sync_summary=result.value or {},
    )
    return result


def _record_failure(integration: Integration, message: str) -> None:
    _record(integration, last_sync_status=Integration.SyncStatus.FAILED, last_sync_error=message)


def _record(integration: Integration, **fields: Any) -> None:
    """Write this run's outcome, unless a reconnect has superseded the run.

    ``connected_at`` moves when somebody reconnects, and the callback queues a
    run against the new credential. This run read the old one, so its answer is
    about an account that may not be the connected one any more, and the row
    keeps what the newer run has to say instead.

    A disconnect lands here too: the row is gone, nothing matches, and the run
    ends quietly rather than on a write against a deleted row.
    """
    for field, value in fields.items():
        setattr(integration, field, value)

    Integration.objects.filter(pk=integration.pk, connected_at=integration.connected_at).update(
        updated_at=timezone.now(), **fields
    )
