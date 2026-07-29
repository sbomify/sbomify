"""Maintaining :class:`VulnerabilityLifecycle` as scan results arrive.

Findings exist per run only, so nothing recorded when a vulnerability first
appeared for a component or when it stopped appearing, and neither "age of open
criticals" nor MTTR could be computed.

**The trap this module exists to avoid: absent from a scan does not mean fixed.**

The obvious rule, "anything not in the latest scan is resolved", is wrong in a
way that flatters the numbers precisely when scanning is broken:

* Dependency Track handed an SPDX SBOM returns a *skipped* result with zero
  findings, so every DT finding vanishes at once.
* A plugin disabled for the workspace stops reporting entirely.
* An outage or a failed run produces nothing.

Under the naive rule each of those marks a whole component remediated, and MTTR
improves. So a run only closes findings when it actually scanned: completed, not
skipped, and belonging to the plugin whose findings are being compared. A
skipped or failed run updates nothing at all, which is the honest outcome, since
it carries no evidence either way.

Resolution is also scoped per plugin. OSV and Dependency Track see different
things, so OSV's results must not close findings only DT ever reported.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from sbomify.logging import getLogger

logger = getLogger(__name__)


def run_scanned(run: Any) -> bool:
    """Whether this run carries evidence about what is and is not present.

    A skipped run reports one stand-down notice and no findings; treating that
    as "nothing found" is what would mark a component remediated because its
    format changed.
    """
    if getattr(run, "status", None) != "completed":
        return False
    result = getattr(run, "result", None)
    if not isinstance(result, dict):
        return False
    metadata = result.get("metadata")
    if isinstance(metadata, dict) and metadata.get("skipped"):
        return False
    return True


def _advisories(result: dict[str, Any]) -> dict[str, str]:
    """Advisory id to severity for the real vulnerabilities in a result."""
    from sbomify.apps.vulnerability_scanning.posture import _is_vulnerability

    seen: dict[str, str] = {}
    for finding in result.get("findings") or []:
        if not isinstance(finding, dict) or not _is_vulnerability(finding):
            continue
        advisory_id = (finding.get("id") or "").strip()
        if advisory_id:
            seen[advisory_id] = (finding.get("severity") or "").lower()
    return seen


@transaction.atomic
def record_run(run: Any) -> dict[str, int]:
    """Fold one completed run into the component's lifecycle rows.

    Returns counts of what changed, which is what the tests assert against and
    what makes a no-op run visible in logs.
    """
    from sbomify.apps.plugins.models import VulnerabilityLifecycle

    if not run_scanned(run):
        logger.debug(f"[LIFECYCLE] run {getattr(run, 'id', '?')} carries no evidence; leaving lifecycle untouched")
        return {"opened": 0, "seen": 0, "resolved": 0}

    sbom = getattr(run, "sbom", None)
    component_id = getattr(sbom, "component_id", None)
    if component_id is None:
        return {"opened": 0, "seen": 0, "resolved": 0}

    now = timezone.now()
    present = _advisories(run.result)

    existing = {
        row.advisory_id: row
        for row in VulnerabilityLifecycle.objects.select_for_update().filter(component_id=component_id)
    }

    opened = seen = 0
    for advisory_id, severity in present.items():
        row = existing.get(advisory_id)
        if row is None:
            VulnerabilityLifecycle.objects.create(
                component_id=component_id,
                advisory_id=advisory_id,
                severity=severity,
                first_seen_at=now,
                last_seen_at=now,
            )
            opened += 1
            continue
        row.last_seen_at = now
        row.severity = severity or row.severity
        # A finding that comes back was not resolved after all. Clearing the
        # date rather than opening a second row keeps first_seen_at meaning
        # "when this component first had this problem".
        row.resolved_at = None
        row.save(update_fields=["last_seen_at", "severity", "resolved_at"])
        seen += 1

    # Only close what this plugin could have reported. OSV and Dependency Track
    # see different things, so one must not resolve the other's findings.
    plugin_advisories = _advisories_reported_by(component_id, run.plugin_name)
    stale = [
        row
        for advisory_id, row in existing.items()
        if advisory_id not in present and row.resolved_at is None and advisory_id in plugin_advisories
    ]
    for row in stale:
        row.resolved_at = now
        row.save(update_fields=["resolved_at"])

    logger.info(
        f"[LIFECYCLE] component {component_id} via {run.plugin_name}: "
        f"{opened} opened, {seen} still present, {len(stale)} resolved"
    )
    return {"opened": opened, "seen": seen, "resolved": len(stale)}


def _advisories_reported_by(component_id: str, plugin_name: str) -> set[str]:
    """Advisory ids this plugin has ever reported for this component.

    Without this a scanner that never saw a finding would close it.

    Deliberately not DISTINCT ON: that is Postgres-only and would not run on
    SQLite, and the set is bounded anyway now that retention caps runs per
    (sbom, plugin).
    """
    from sbomify.apps.plugins.models import AssessmentRun

    runs = AssessmentRun.objects.filter(
        sbom__component_id=component_id, plugin_name=plugin_name, status="completed"
    ).values_list("result", flat=True)
    reported: set[str] = set()
    for result in runs:
        if isinstance(result, dict):
            reported.update(_advisories(result))
    return reported
