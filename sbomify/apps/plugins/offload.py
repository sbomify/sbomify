"""Move superseded assessment results out of Postgres and into object storage.

The table's bulk is not its rows, it is one column. A scheduled scan writes a
fresh result per SBOM per cycle, each carrying the whole findings array, and
those payloads are read on demand rather than queried — the slices anything
aggregates over were denormalised into ``result_summary`` and ``result_skipped``
so readers would stop touching the blob.

So this demotes the payload of runs that are no longer the current answer for
anything, leaving the row and its summary columns exactly where they are. Such a
run has no ``Finding`` rows to leave: a newer run of its key supersedes it, and
the projection drops a superseded run's rows (``findings.sync_findings``).
See :mod:`sbomify.apps.plugins.result_store` for where the bytes go and why
the keys are shaped as they are.

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

from django.utils import timezone

from sbomify.logging import getLogger

logger = getLogger(__name__)

# How old a superseded run must be before its payload is demoted.
#
# A day, so a run superseded minutes ago is not moved while a VEX re-annotation
# or a release attach may still be settling on it; neither needs it inline (both
# read and write through the result store), so this is a margin, not a guarantee
# anything depends on.
#
# It was 366 while the dashboard drill-down read every payload in its window
# straight from the column, which made this sweep unusable: with a scanner
# polling every hour, nearly every byte in the table is a superseded run inside
# that year. The drill-down now reads offloaded findings too, once per distinct
# findings array, so the floor no longer has to cover what anybody reads.
DEFAULT_OFFLOAD_AFTER_DAYS = 1


def _no_payload_filter() -> dict[str, Any]:
    """Rows carrying no result payload: nothing inline and nothing offloaded."""
    return {"result__isnull": True, "result_object_key": ""}


def current_run_ids(sbom_ids: set[Any], plugin_names: set[str]) -> set[Any]:
    """Ids of the runs that are still the current payload for their key.

    Scoped to the given SBOMs and plugins so the sweep can answer this for a
    batch without ranking every run in the installation. Passing a superset of
    pairs is harmless: grouping is on the exact key.

    A release attached later can change the answer for a run already moved.
    The attach task adds the release to each plugin's newest run, so an older
    run that newest one superseded becomes the newest of the set it left. That
    is safe because of who reads what. Every reader of the payload column ranks
    per (sbom, plugin) and ignores release sets, so it lands on the newer run,
    which is current for its own key. The VEX re-apply skips it too, because the
    newer run now covers every release it covers (plugins.latest), and it reads
    and writes through the result store for the runs it does rewrite. An attach a
    week after the sweep leaves the same state, so a lock here would not prevent it.
    """
    from sbomify.apps.plugins.latest import release_sets
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.sdk.enums import RunStatus

    if not sbom_ids or not plugin_names:
        return set()

    candidates = AssessmentRun.objects.filter(sbom_id__in=sbom_ids, plugin_name__in=plugin_names).exclude(
        **_no_payload_filter()
    )

    # One query for every association rather than one per run. The release set
    # cannot be grouped on in SQL, which is why the ranking happens here.
    releases_by_run = release_sets(candidates.values_list("id", flat=True))

    # Newest first, ``-id`` breaking ties: runs written in one transaction share
    # a timestamp, and an unstable order there would protect the wrong row.
    #
    # Three runs per key are current: the newest of any status, the newest
    # completed one, and the newest completed one that was not skipped. The
    # findings readers ask for the latest completed run, and a failed run can
    # carry a synthesised result, so a newer failure would otherwise demote the
    # run those readers still resolve to. The lifecycle peer check ignores
    # skipped runs and reads the payload column, so a newer skip would do the same.
    current: set[Any] = set()
    seen: set[tuple[Any, str, frozenset[Any]]] = set()
    seen_completed: set[tuple[Any, str, frozenset[Any]]] = set()
    seen_scanned: set[tuple[Any, str, frozenset[Any]]] = set()
    for run_id, sbom_id, plugin_name, status, skipped in (
        candidates.order_by("-created_at", "-id")
        .values_list("id", "sbom_id", "plugin_name", "status", "result_skipped")
        .iterator()
    ):
        # A run that completed after the release lookup has none recorded yet.
        key = (sbom_id, plugin_name, releases_by_run.get(run_id, frozenset()))
        if key not in seen:
            seen.add(key)
            current.add(run_id)
        if status == RunStatus.COMPLETED.value and key not in seen_completed:
            seen_completed.add(key)
            current.add(run_id)
        # ``is not True``, as the peer check's exclude() reads it: a legacy NULL counts as scanned.
        if status == RunStatus.COMPLETED.value and skipped is not True and key not in seen_scanned:
            seen_scanned.add(key)
            current.add(run_id)
    return current


def demotable_run_ids(*, older_than_days: int = DEFAULT_OFFLOAD_AFTER_DAYS, limit: int | None = None) -> list[Any]:
    """Ids whose payload is safe to move: inline, past the floor, superseded.

    Returned rather than acted on, so the policy can be inspected without being
    welded to the write. This holds every id it returns; the sweep itself walks
    :func:`demotable_batches` a page at a time.
    """
    return [run_id for batch in demotable_batches(older_than_days=older_than_days, limit=limit) for run_id in batch]


def demotable_batches(
    *, older_than_days: int = DEFAULT_OFFLOAD_AFTER_DAYS, batch_size: int = 100, limit: int | None = None
) -> Iterator[list[Any]]:
    """The demotable ids, one page of candidates at a time, oldest first.

    A first pass covers the whole historical backlog, so the candidates are
    paged rather than loaded, and each page is ranked against the runs of its
    own SBOMs and plugins. Paged on ``(created_at, id)`` rather than by offset:
    a protected run stays a candidate, so an offset would skip rows once the
    pages before it had been demoted.
    """
    from django.db.models import Q

    from sbomify.apps.plugins.models import AssessmentRun

    cutoff = timezone.now() - timedelta(days=max(0, older_than_days))
    candidates = (
        AssessmentRun.objects.filter(result_object_key="", created_at__lt=cutoff)
        .exclude(result__isnull=True)
        # Oldest first: the coldest rows are the least likely to be contended and
        # the most likely to still be here on the next pass if this one stops.
        .order_by("created_at", "id")
    )
    page_size = max(1, batch_size)
    remaining = limit
    after = Q()
    while remaining is None or remaining > 0:
        size = page_size if remaining is None else min(page_size, remaining)
        page = list(candidates.filter(after).values_list("id", "sbom_id", "plugin_name", "created_at")[:size])
        if not page:
            return
        if remaining is not None:
            remaining -= len(page)
        last_id, _, _, last_created = page[-1]
        # The leading >= is what the index can start from; the OR alone is a filter.
        after = Q(created_at__gte=last_created) & (Q(created_at__gt=last_created) | Q(id__gt=last_id))
        protected = current_run_ids({sbom_id for _, sbom_id, _, _ in page}, {plugin for _, _, plugin, _ in page})
        yield [run_id for run_id, _, _, _ in page if run_id not in protected]


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
    a retry cannot double-apply, and on the row still holding the payload that
    was read, so a VEX re-annotation landing in between makes it miss rather
    than be discarded. The next pass offloads the rewrite. That guard is what
    lets ``put_result`` run outside any transaction.

    A miss keeps the object it stored whenever the row reads any key. Another
    sweep moving the same payload lands on this key, and a VEX rewrite after
    that moves the row on while keeping this object as its prior revision. A
    miss on a row still inline, or one a prune deleted, deletes it: nothing
    points at it, and the orphan sweep only collects objects of deleted runs,
    so it would otherwise stay until the run did.
    """
    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.result_store import delete_result_object, put_split_result

    payload = run.result
    if not isinstance(payload, dict):
        return False

    with put_split_result(run.id, payload) as stored:
        run._populate_result_columns()
        changed = AssessmentRun.objects.filter(pk=run.pk, result_object_key="", result=payload).update(
            result=None,
            result_summary=run.result_summary,
            result_skipped=run.result_skipped,
            result_object_key=stored.key,
            result_findings_key=stored.findings_key,
        )
        if not changed and not AssessmentRun.objects.filter(pk=run.pk).exclude(result_object_key="").exists():
            # The shared findings object is left for the daily collector, which
            # removes it once no row names it.
            delete_result_object(stored.key)
    return bool(changed)


def offload_assessment_results(
    *,
    older_than_days: int = DEFAULT_OFFLOAD_AFTER_DAYS,
    batch_size: int = 100,
    limit: int | None = None,
    dry_run: bool = False,
    max_seconds: float | None = None,
) -> int:
    """Demote payloads in batches. Returns how many rows were changed.

    Batched so an interruption costs at most one batch. No transaction is held
    across a batch: each row's store is an object storage round trip, and each
    write is one guarded UPDATE (see :func:`offload_run`).

    ``max_seconds`` stops between rows once the budget is spent, so the
    scheduled task ends cleanly inside its time limit rather than being killed
    mid-store; the next pass carries on from the oldest row left.
    """
    import time

    deadline = time.monotonic() + max_seconds if max_seconds is not None else None
    batches = demotable_batches(older_than_days=older_than_days, batch_size=batch_size, limit=limit)
    if dry_run:
        count = sum(len(batch) for batch in batches)
        logger.info(f"[OFFLOAD] dry run: {count} assessment results would be offloaded")
        return count

    from sbomify.apps.plugins.models import AssessmentRun

    moved = 0
    for batch in batches:
        # Deferring nothing on purpose: the payload is what is being read.
        for run in AssessmentRun.objects.filter(id__in=batch, result_object_key="").iterator():
            if deadline is not None and time.monotonic() >= deadline:
                logger.info(f"[OFFLOAD] time budget spent after {moved} assessment results")
                return moved
            if offload_run(run):
                moved += 1
    if moved:
        logger.info(f"[OFFLOAD] offloaded {moved} assessment results")
    return moved
