"""Tell a workspace's open pages that an assessment run has settled.

Every page that shows a run's state ("Processing", a findings count) repaints on
``assessment_complete``. A run can settle in more ways than finishing normally:
retries run out, the plugin skips the artifact and its eager pending row is
removed, the orchestrator gives up, or the stranded sweep finalises it. Each of
those leaves the page spinning until a reload unless it is announced too.
"""

from __future__ import annotations

from sbomify.apps.core.utils import broadcast_to_workspace
from sbomify.logging import getLogger

logger = getLogger(__name__)


def announce_assessment_settled(sbom_id: str, plugin_name: str, status: str) -> None:
    """Broadcast ``assessment_complete`` for one SBOM. Never raises."""
    from sbomify.apps.sboms.models import SBOM

    try:
        row = SBOM.objects.filter(pk=sbom_id).values("component_id", "component__team__key").first()
        if not row or not row["component__team__key"]:
            return
        broadcast_to_workspace(
            workspace_key=row["component__team__key"],
            message_type="assessment_complete",
            data={
                "sbom_id": str(sbom_id),
                "component_id": str(row["component_id"]),
                "plugin_name": plugin_name,
                "status": status,
            },
        )
    except Exception:
        logger.warning("Could not announce settled assessment for SBOM %s", sbom_id, exc_info=True)
