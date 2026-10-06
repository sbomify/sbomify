"""Plugins a workspace has not seen on its settings page yet.

Plugins stay opt-in, so a plugin registered after a workspace last saved its
settings is marked new there rather than switched on.
"""

from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.plugins.models import RegisteredPlugin, TeamPluginSettings


def plugins_added_since_last_save(team_key: str) -> ServiceResult[set[str]]:
    """Names of the plugins registered after the workspace last saved its plugin settings."""
    saved_at = TeamPluginSettings.objects.filter(team__key=team_key).values_list("updated_at", flat=True).first()
    if saved_at is None:
        return ServiceResult.success(set())
    return ServiceResult.success(
        set(RegisteredPlugin.objects.filter(is_enabled=True, created_at__gt=saved_at).values_list("name", flat=True))
    )
