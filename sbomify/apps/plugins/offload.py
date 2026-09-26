"""Move superseded assessment results out of Postgres and into object storage.

The table's bulk is not its rows, it is one column. A scheduled scan writes a
fresh result per SBOM per cycle, each carrying the whole findings array, and
those payloads are read on demand rather than queried — the slices anything
aggregates over were denormalised into ``result_summary`` and ``result_skipped``
so readers would stop touching the blob.

So this demotes the payload of runs that are no longer the current answer for
anything, leaving the row, its summary columns and its normalised ``Finding``
rows exactly where they are. See :mod:`sbomify.apps.plugins.result_store` for
where the bytes go and why the keys are shaped as they are.

**What counts as current is (sbom, plugin, release set), not (sbom, plugin).**
One SBOM can sit in two releases at once with different per-release triage, and
the VEX re-annotation keeps a live run for each of those contexts — each is the
result for its own release, whatever their relative age. Demoting one because a
run of the same pair is newer would take the payload of a row that a VEX upload
is still expected to rewrite.

**This is not a migration; it is a sweep that has to keep running.** Every new
run supersedes the previous current run of its key, so there is always a fresh
tail to demote. The historical backlog is simply this sweep's first pass, which
is also why it is written to be interrupted and re-run at any point rather than
as a one-shot data migration.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from sbomify.logging import getLogger

logger = getLogger(__name__)

# How old a superseded run must be before its payload is demoted.
#
# Deliberately longer than the furthest back any reader can currently ask. The
# dashboard drill-down accepts ``days`` up to 365 and renders findings for every
# run in that window from the stored payload, so a shorter floor would make it
# read an empty findings list for runs whose payload had moved. Its fields
# (title, reference URL) are not carried by the normalised ``Finding`` rows, so
# it cannot simply be pointed at those; until it is, this floor is what keeps the
# sweep from changing what anybody sees.
#
# Lowering it is where the space actually is, and it is a one-line change once
# the drill-down no longer reads payloads. Do not lower it before then.
DEFAULT_OFFLOAD_AFTER_DAYS = 366


def _has_payload_filter() -> dict[str, Any]:
    """Rows carrying a result payload, inline or offloaded."""
    return {"result__isnull": True, "result_object_key": ""}


def current_run_ids(sbom_ids: set[Any], plugin_names: set[str]) -> set[Any]:
    """Ids of the runs that are still the current payload for their key.

    Scoped to the given SBOMs and plugins so the sweep can answer this for a
    batch without ranking every run in the installation. Passing a superset of
    pairs is harmless: grouping is on the exact key.
    """
    from sbomify.apps.plugins.models import AssessmentRun, AssessmentRunRelease

    if not sbom_ids or not plugin_names:
        return set()

    candidates = AssessmentRun.objects.filter(sbom_id__in=sbom_ids, plugin_name__in=plugin_names).exclude(
        **_has_payload_filter()
    )

    # One query for every association rather than one per run. The release set
    # cannot be grouped on in SQL, which is why the ranking happens here.
    releases_by_run: dict[Any, set[Any]] = {}
    for run_id, release_id in AssessmentRunRelease.objects.filter(
        assessment_run__in=candidates.values("id")
    ).values_list("assessment_run_id", "release_id"):
        releases_by_run.setdefault(run_id, set()).add(release_id)

    # Newest first, ``-id`` breaking ties: runs written in one transaction share
    # a timestamp, and an unstable order there would protect the wrong row.
    current: set[Any] = set()
    seen: set[tuple[Any, str, frozenset[Any]]] = set()
    for run_id, sbom_id, plugin_name in (
        candidates.order_by("-created_at", "-id").values_list("id", "sbom_id", "plugin_name").iterator()
    ):
        key = (sbom_id, plugin_name, frozenset(releases_by_run.get(run_id, ())))
        if key in seen:
            continue
        seen.add(key)
        current.add(run_id)
    return current


def demotable_run_ids(*, older_than_days: int = DEFAULT_OFFLOAD_AFTER_DAYS, limit: int | None = None) -> list[Any]:
    """Ids whose payload is safe to move: inline, past the floor, superseded.

    Returned rather than acted on, so the policy can be counted and dry-run
    without being welded to the write.
    """
    from sbomify.apps.plugins.models import AssessmentRun

    cutoff = timezone.now() - timedelta(days=max(0, older_than_days))
    rows = (
        AssessmentRun.objects.filter(result_object_key="", created_at__lt=cutoff)
        .exclude(result__isnull=True)
        # Oldest first: the coldest rows are the least likely to be contended and
        # the most likely to still be here on the next pass if this one stops.
        .order_by("created_at", "id")
        .values_list("id", "sbom_id", "plugin_name")
    )
    candidates = list(rows[:limit] if limit is not None else rows)
    if not candidates:
        return []

    protected = current_run_ids(
        {sbom_id for _, sbom_id, _ in candidates},
        {plugin_name for _, _, plugin_name in candidates},
    )
    return [run_id for run_id, _, _ in candidates if run_id not in protected]


def offload_run(run: Any) -> bool:
    """Move one run's payload to object storage. Returns whether the row changed.

    Ordering is the whole safety argument:

    1. The payload is stored first, and the key is its content hash, so storing
       it twice is storing it once.
    2. The summary columns are recomputed from the payload while it is still in
       hand. A row written before those columns existed has them NULL, and
       nulling its payload without filling them first would lose its counts for
       good. Doing it here rather than relying on a backfill having been run
       first means the sweep cannot be started in the wrong order.
    3. One UPDATE writes the key and nulls the payload together, so there is no
       instant at which a row has neither, and no path that nulls a payload
       whose key is not committed.

    The UPDATE is guarded on the key still being empty, so a concurrent sweep or
    a retry cannot double-apply.
    """
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.result_store import put_result

    payload = run.result
    if not isinstance(payload, dict):
        return False

    key = put_result(run.id, payload)
    run._populate_result_columns()
    changed = AssessmentRun.objects.filter(pk=run.pk, result_object_key="").update(
        result=None,
        result_summary=run.result_summary,
        result_skipped=run.result_skipped,
        result_object_key=key,
    )
    return bool(changed)


def offload_assessment_results(
    *,
    older_than_days: int = DEFAULT_OFFLOAD_AFTER_DAYS,
    batch_size: int = 100,
    limit: int | None = None,
    dry_run: bool = False,
) -> int:
    """Demote payloads in batches. Returns how many rows were changed.

    Batched so a first pass over a large table holds a series of short locks
    rather than one long one, and so an interruption costs at most one batch.
    Each batch takes ``select_for_update`` on its rows for the read-store-write
    cycle, so a concurrent VEX re-annotation cannot land between reading the
    payload and nulling it and be silently discarded.
    """
    doomed = demotable_run_ids(older_than_days=older_than_days, limit=limit)
    if dry_run:
        logger.info(f"[OFFLOAD] dry run: {len(doomed)} assessment results would be offloaded")
        return len(doomed)

    moved = 0
    for batch in _batched(doomed, max(1, batch_size)):
        with transaction.atomic():
            for run in (
                _runs_for_update(batch)
                # Deferring nothing on purpose: the payload is what is being read.
                .iterator()
            ):
                if offload_run(run):
                    moved += 1
    if moved:
        logger.info(f"[OFFLOAD] offloaded {moved} assessment results")
    return moved


def _runs_for_update(ids: list[Any]) -> Any:
    from sbomify.apps.plugins.models import AssessmentRun

    return AssessmentRun.objects.filter(id__in=ids, result_object_key="").select_for_update()


def _batched(items: list[Any], size: int) -> Iterator[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
