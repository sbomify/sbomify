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

    integration.last_sync_status = Integration.SyncStatus.RUNNING
    integration.save(update_fields=["last_sync_status", "updated_at"])

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

    integration.last_sync_status = Integration.SyncStatus.OK
    integration.last_sync_at = timezone.now()
    integration.last_sync_error = ""
    integration.last_sync_summary = result.value or {}
    integration.save(
        update_fields=["last_sync_status", "last_sync_at", "last_sync_error", "last_sync_summary", "updated_at"]
    )
    return result


def _record_failure(integration: Integration, message: str) -> None:
    integration.last_sync_status = Integration.SyncStatus.FAILED
    integration.last_sync_error = message
    integration.save(update_fields=["last_sync_status", "last_sync_error", "updated_at"])
