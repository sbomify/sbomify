"""Which of a workspace's plugins an artifact's assessments card is missing.

The card lists stored runs, so on its own it cannot show a plugin that never ran
(enabled after the upload, or skipped because nothing was scheduled) or tell a
result from an older plugin version apart from a current one. Nothing here runs
anything: a plugin with no run is offered as a manual run, and an out-of-date
result as a re-run, through the same endpoint the card already uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.utils.module_loading import import_string

from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Team
from sbomify.logging import getLogger

from ..models import RegisteredPlugin, TeamPluginSettings
from ..orchestrator import plugin_applies_to
from .access import team_has_plugin_access

logger = getLogger(__name__)


@dataclass(frozen=True)
class AssessmentCoverage:
    """What the card needs beyond the stored runs.

    ``plugins_enabled`` is whether the workspace has any plugin turned on that
    its plan includes. ``plan_excludes_plugins`` is whether it has plugins turned
    on but its plan includes none of them, as after a downgrade. ``unassessed``
    lists the ones that apply to this artifact and have no run for it, as
    ``{"plugin_name", "plugin_display_name"}``.
    ``outdated`` maps a plugin name to its current version, for each latest run
    produced by a different one. ``runnable`` names every plugin the re-run
    endpoint would accept for this workspace.
    """

    plugins_enabled: bool = False
    plan_excludes_plugins: bool = False
    unassessed: list[dict[str, str]] = field(default_factory=list)
    outdated: dict[str, str] = field(default_factory=dict)
    runnable: frozenset[str] = frozenset()


def get_assessment_coverage(
    sbom_id: str, team: Team, latest_runs: list[dict[str, Any]]
) -> ServiceResult[AssessmentCoverage]:
    """Compare an artifact's latest runs with the plugins its workspace runs.

    A plugin is offered only when the re-run endpoint would accept it (enabled
    in the registry and for the workspace), the workspace's plan includes it,
    and the orchestrator would not skip it for this artifact's type.
    """
    sbom = SBOM.objects.filter(id=sbom_id).only("id", "bom_type", "has_crypto_assets").first()
    if sbom is None:
        return ServiceResult.failure("SBOM not found", status_code=404)

    settings = TeamPluginSettings.objects.filter(team=team).first()
    enabled = (settings.enabled_plugins or []) if settings else []
    registered = {p.name: p for p in RegisteredPlugin.objects.filter(is_enabled=True, name__in=enabled)}
    offered = [registered[name] for name in enabled if name in registered and team_has_plugin_access(team, name)]

    runs = {run["plugin_name"]: run for run in latest_runs}
    unassessed: list[dict[str, str]] = []
    outdated: dict[str, str] = {}
    for plugin in offered:
        run = runs.get(plugin.name)
        if run is not None:
            if run["status"] == "completed" and run["plugin_version"] != plugin.version:
                outdated[plugin.name] = plugin.version
            continue
        try:
            metadata = import_string(plugin.plugin_class_path)().get_metadata()
        except Exception:
            logger.exception("Could not load plugin %s to check whether it applies", plugin.name)
            continue
        if plugin_applies_to(metadata, sbom.bom_type, sbom.has_crypto_assets):
            unassessed.append({"plugin_name": plugin.name, "plugin_display_name": plugin.display_name})

    return ServiceResult.success(
        AssessmentCoverage(
            plugins_enabled=bool(offered),
            plan_excludes_plugins=bool(registered) and not offered,
            unassessed=unassessed,
            outdated=outdated,
            runnable=frozenset(plugin.name for plugin in offered),
        )
    )
