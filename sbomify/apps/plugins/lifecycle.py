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

Resolution also answers to the other scanners. OSV and Dependency Track see
different things, so a finding closes only when no other plugin's most recent
real scan still reports it.

The rows are keyed per component rather than per plugin on purpose. "CVE-X
affects this component" is one fact about the component; splitting it per
scanner would count the same vulnerability twice in the open-criticals age and
twice in MTTR, and would make first_seen_at mean "when this scanner noticed"
rather than "when the component got the problem".
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from sbomify.apps.plugins.sdk.enums import RunStatus
from sbomify.logging import getLogger

logger = getLogger(__name__)


def run_scanned(run: Any) -> bool:
    """Whether this run carries evidence about what is and is not present.

    A skipped run reports one stand-down notice and no findings; treating that
    as "nothing found" is what would mark a component remediated because its
    format changed.

    A run that errored says just as little, and said it while looking like a
    completed scan: plugins record a failure by returning a result with
    ``error_count`` set and the status still COMPLETED, so only the summary
    distinguishes "scanned and found nothing" from "could not scan". Without
    this an aborted osv-scanner run resolved every open advisory for the
    component — a remediation that never happened, dropping real CVEs out of
    the workspace's open counts and into its MTTR.
    """
    if getattr(run, "status", None) != RunStatus.COMPLETED.value:
        return False
    result = getattr(run, "result", None)
    if not isinstance(result, dict):
        return False
    metadata = result.get("metadata")
    if isinstance(metadata, dict) and metadata.get("skipped"):
        return False
    summary = result.get("summary")
    if isinstance(summary, dict) and summary.get("error_count"):
        return False
    return True


def _advisories(result: dict[str, Any]) -> dict[str, str]:
    """Advisory id to severity for the real vulnerabilities in a result."""
    from sbomify.apps.vulnerability_scanning.utils import is_vulnerability

    seen: dict[str, str] = {}
    for finding in result.get("findings") or []:
        if not isinstance(finding, dict) or not is_vulnerability(finding):
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

    # One gate lock on the component row before touching its lifecycle rows.
    # Two concurrent folds for the same component deadlocked on stage: the
    # per-row FOR UPDATE below locks in whatever order the planner scans, so
    # two identical scans can interleave into an AB/BA wait — and two runs
    # inserting the same new advisory would race the unique constraint. The
    # caller swallows failures to protect the stored run, so a lost fold left
    # no trace beyond a warning. Folds are order-dependent by nature; making
    # them queue here is the semantics, not a cost.
    from sbomify.apps.core.models import Component

    Component.objects.select_for_update().filter(pk=component_id).first()

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

    # Only close what no other scanner still reports. OSV and Dependency Track
    # see different things, so one must not resolve the other's findings.
    peers = _still_reported_by_peers(component_id, run.plugin_name)
    stale = [
        row
        for advisory_id, row in existing.items()
        if advisory_id not in present and row.resolved_at is None and advisory_id not in peers
    ]
    for row in stale:
        row.resolved_at = now
        row.save(update_fields=["resolved_at"])

    logger.info(
        f"[LIFECYCLE] component {component_id} via {run.plugin_name}: "
        f"{opened} opened, {seen} still present, {len(stale)} resolved"
    )
    return {"opened": opened, "seen": seen, "resolved": len(stale)}


def _still_reported_by_peers(component_id: str, plugin_name: str) -> set[str]:
    """What the other plugins' most recent real scans still report.

    Anything in here is off limits: some scanner looked recently and the
    finding was there, so the current plugin dropping it says only that this
    scanner no longer sees it.

    Only each peer's newest scanned run counts. Skipped and failed runs are
    excluded rather than treated as clean, so a peer handed an SPDX SBOM falls
    back to its last real evidence instead of silently releasing the finding.

    Two phases so the fat ``result`` blob is fetched once per peer instead of
    once per run: the ids are picked from small columns first. Deliberately not
    DISTINCT ON, which is Postgres-only.
    """
    from sbomify.apps.plugins.models import AssessmentRun

    candidates = (
        AssessmentRun.objects.filter(sbom__component_id=component_id, status=RunStatus.COMPLETED.value)
        .exclude(plugin_name=plugin_name)
        .exclude(result_skipped=True)
        .order_by("plugin_name", "-created_at", "-id")
        .values_list("id", "plugin_name")
    )
    newest_per_peer: dict[str, Any] = {}
    for run_id, peer in candidates:
        newest_per_peer.setdefault(peer, run_id)
    if not newest_per_peer:
        return set()

    reported: set[str] = set()
    for result in AssessmentRun.objects.filter(id__in=newest_per_peer.values()).values_list("result", flat=True):
        if isinstance(result, dict):
            reported.update(_advisories(result))
    return reported
