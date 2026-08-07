"""Retention for ``plugins_assessment_runs`` and Dependency-Track project versions.

The table only grows: every scan, every retry, every scheduled run. It was at
roughly 10,300 rows climbing ~170/day when #1120 was filed, with no policy at
all, which feeds TOAST bloat, index growth and the long checkpoints seen on
staging.

Two rules, deliberately both:

* **Keep the newest N runs per (sbom, plugin).** History is only interesting per
  scanner: keeping "the newest N for this SBOM" would let a chatty plugin evict
  a quiet one's only run.
* **Never delete anything inside the TTL floor**, however many runs there are. A
  burst of retries in one afternoon must not erase the run from that morning
  which someone is still looking at.

A run is deleted only when *both* rules agree, so the pair is a floor rather
than a race. The newest run per (sbom, plugin) can never qualify whatever its
age, because deleting it would empty a card with no newer result to replace it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from sbomify.logging import getLogger

logger = getLogger(__name__)

# Enough to show a trend on a card without keeping every retry storm.
DEFAULT_KEEP_PER_PLUGIN = 10

# Nothing newer than this is touched, regardless of how many runs exist.
DEFAULT_MIN_AGE_DAYS = 30

# Same floor for DT project versions, for a different reason: an SBOM is
# uploaded and scanned before ``sync_release_tags`` attaches it to a release,
# and pruning inside that window would delete the project a running scan polls.
DEFAULT_DT_MIN_AGE_DAYS = 30


def prunable_run_ids(
    *,
    keep_per_plugin: int = DEFAULT_KEEP_PER_PLUGIN,
    min_age_days: int = DEFAULT_MIN_AGE_DAYS,
) -> list[Any]:
    """Ids safe to delete under both rules.

    Returns ids rather than deleting them, so the policy can be counted or
    dry-run without being welded to the deletion.

    One pass over every run, newest first within each (sbom, plugin). The sort
    breaks ties on id, because runs created in the same transaction can share a
    timestamp and an unstable order there would let a newer row rank below an
    older one and be pruned. Ranking
    against *all* runs rather than only the old ones is what makes the two rules
    compose: a pair whose quota is already filled by recent runs has its older
    ones prunable, while a pair with few runs keeps them however old they are.
    Only the four small columns are selected, so the fat ``result`` blob is
    never fetched.
    """
    from sbomify.apps.plugins.models import AssessmentRun

    # A quota of 0 would make rank>=0 true for the newest run, contradicting the
    # guarantee above; a negative floor would push the cutoff into the future
    # and make everything eligible. Clamp rather than trust the caller, since
    # both mistakes delete data.
    keep_per_plugin = max(1, keep_per_plugin)
    min_age_days = max(0, min_age_days)

    cutoff = timezone.now() - timedelta(days=min_age_days)

    rows = (
        AssessmentRun.objects.order_by("sbom_id", "plugin_name", "-created_at", "-id")
        .values_list("id", "sbom_id", "plugin_name", "created_at")
        .iterator()
    )

    doomed: list[Any] = []
    current_pair: tuple[str, str] | None = None
    rank = 0
    for run_id, sbom_id, plugin_name, created_at in rows:
        pair = (sbom_id, plugin_name)
        if pair != current_pair:
            current_pair, rank = pair, 0
        else:
            rank += 1
        if rank >= keep_per_plugin and created_at < cutoff:
            doomed.append(run_id)
    return doomed


def prune_assessment_runs(
    *,
    keep_per_plugin: int = DEFAULT_KEEP_PER_PLUGIN,
    min_age_days: int = DEFAULT_MIN_AGE_DAYS,
    batch_size: int = 500,
    dry_run: bool = False,
) -> int:
    """Delete prunable runs in batches. Returns how many were removed.

    Batched so the first run against a large table holds a series of short
    locks rather than one long one, which is the failure mode that made the
    original #1120 migration unrunnable on staging.
    """
    from sbomify.apps.plugins.models import AssessmentRun

    doomed = prunable_run_ids(keep_per_plugin=keep_per_plugin, min_age_days=min_age_days)
    if dry_run:
        logger.info(f"[RETENTION] dry run: {len(doomed)} assessment runs would be pruned")
        return len(doomed)

    batch_size = max(1, batch_size)
    removed = 0
    for start in range(0, len(doomed), batch_size):
        batch = doomed[start : start + batch_size]
        # Count what the delete actually removed, not what was asked for: a
        # concurrent sweep may already have taken some of these rows.
        _, per_model = AssessmentRun.objects.filter(id__in=batch).delete()
        removed += per_model.get("plugins.AssessmentRun", 0)
    if removed:
        logger.info(f"[RETENTION] pruned {removed} assessment runs")
    return removed


def prunable_dt_project_version_ids(*, min_age_days: int = DEFAULT_DT_MIN_AGE_DAYS) -> list[Any]:
    """Project-version ids whose SBOM has fallen out of every current release.

    Dependency-Track re-analyses its whole portfolio on its own schedule, so its
    CPU cost grows with every SBOM ever uploaded, whether or not anyone reads the
    result. That is a load floor our own sweep cadence cannot lower.

    Dropping a version costs nothing a reader can see: findings are already
    stored in ``AssessmentRun`` and the Trust Center reads those, so a pruned
    SBOM keeps its posture. A later scan recreates the project.

    Ids rather than rows, matching ``prunable_run_ids``, so the policy can be
    counted or dry-run without being welded to the deletion.
    """
    from django.db.models import Exists, OuterRef

    from sbomify.apps.core.models import ReleaseArtifact
    from sbomify.apps.vulnerability_scanning.models import SbomDependencyTrackProjectVersion

    cutoff = timezone.now() - timedelta(days=max(0, min_age_days))

    # Exists() rather than a reverse accessor, matching the scheduled sweep:
    # ReleaseArtifact.sbom carries no related_name, so a join here would couple
    # this query to the default accessor name.
    return list(
        SbomDependencyTrackProjectVersion.objects.filter(created_at__lt=cutoff)
        .annotate(
            in_current_release=Exists(
                ReleaseArtifact.objects.filter(sbom_id=OuterRef("sbom_id"), release__is_latest=True)
            )
        )
        .filter(in_current_release=False)
        .values_list("id", flat=True)
    )


def prune_dt_project_versions(
    *,
    min_age_days: int = DEFAULT_DT_MIN_AGE_DAYS,
    dry_run: bool = False,
) -> int:
    """Delete stale DT project versions and their local rows. Returns how many went.

    The local row is dropped only once Dependency-Track has no copy, so a server
    that is down or refusing keeps its rows and the next sweep retries them. A
    404 counts as success: the project is already gone, and leaving the row
    behind would strand it forever.

    One row at a time rather than batched, because each is a network call to a
    server that may be unreachable, and one bad server must not abort the rest.
    """
    from sbomify.apps.vulnerability_scanning.clients import DependencyTrackAPIError, DependencyTrackClient
    from sbomify.apps.vulnerability_scanning.models import SbomDependencyTrackProjectVersion

    doomed = prunable_dt_project_version_ids(min_age_days=min_age_days)
    if dry_run:
        logger.info(f"[RETENTION] dry run: {len(doomed)} DT project versions would be pruned")
        return len(doomed)

    removed = 0
    rows = SbomDependencyTrackProjectVersion.objects.filter(id__in=doomed).select_related("dt_server")
    for row in rows.iterator():
        try:
            client = DependencyTrackClient(row.dt_server.url, row.dt_server.api_key)
            client.delete_project(str(row.dt_project_version_uuid))
        except DependencyTrackAPIError as exc:
            if exc.status_code != 404:
                logger.warning(
                    f"[RETENTION] leaving DT version {row.dt_project_version_uuid} on "
                    f"{row.dt_server.name} for the next sweep: {exc}"
                )
                continue
        except Exception as exc:
            logger.warning(f"[RETENTION] DT delete failed for {row.dt_project_version_uuid}: {exc}")
            continue
        row.delete()
        removed += 1
    if removed:
        logger.info(f"[RETENTION] pruned {removed} DT project versions")
    return removed
