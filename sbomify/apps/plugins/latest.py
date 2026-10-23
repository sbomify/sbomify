"""The newest run per (SBOM, plugin), without reading the run history.

Every page that shows a scan result asks this, and an SBOM rescanned hourly
carries up to 720 runs per plugin inside the retention window. ``DISTINCT ON``
answered it by sorting every run the SBOMs ever had to keep one per pair; on a
million-run table that took 333 ms for 65 SBOMs and 1.4 s for 1,300. One
``LIMIT 1`` probe per pair on the ``(sbom, plugin_name, -created_at)`` index
takes 1.4 ms and 27 ms.
"""

from __future__ import annotations

from typing import Any

from django.db.models import OuterRef, QuerySet, Subquery


def latest_run_ids(runs: QuerySet[Any], sbom_ids: Any) -> list[Any]:
    """Ids of the newest of ``runs`` per (SBOM, plugin), grouped by SBOM, plugins in name order.

    ``runs`` carries the caller's filters, such as category and status, and
    ``sbom_ids`` is any iterable or queryset of SBOM ids. Ties on
    ``created_at`` go to the higher id.

    The plugin names come from the registry, so the runs of a plugin removed
    from it no longer count: they describe a check the platform stopped running.
    """
    from sbomify.apps.plugins.models import RegisteredPlugin
    from sbomify.apps.sboms.models import SBOM

    newest = runs.order_by("-created_at", "-id").values("id")
    probes = {
        f"run_{index}": Subquery(newest.filter(sbom_id=OuterRef("pk"), plugin_name=name)[:1])
        for index, name in enumerate(RegisteredPlugin.objects.order_by("name").values_list("name", flat=True))
    }
    if not probes:
        return []
    rows = SBOM.objects.filter(pk__in=sbom_ids).order_by("pk").annotate(**probes).values_list(*probes)
    return [run_id for row in rows for run_id in row if run_id is not None]


def release_run_ids(runs: QuerySet[Any], sbom_ids: Any, release_id: Any) -> tuple[list[Any], set[Any]]:
    """The runs a release reads for its SBOMs, and which of them cover the release itself.

    Two releases can share an SBOM yet each hold a live run of one scanner, because a
    run is annotated with its own releases' VEX. The newest run overall may then carry
    another release's suppressions, so a release reads the newest run that covers it,
    and falls back to the newest run for a scanner none of whose runs name it. Without
    a release this is :func:`latest_run_ids` and the second set is empty.

    The list, its Triage dialog and its fix prompt all select runs here, so an action
    never reads another scan than the row it was opened from.
    """
    from sbomify.apps.plugins.models import AssessmentRun

    sbom_ids = list(sbom_ids)
    latest_ids = latest_run_ids(runs, sbom_ids)
    if not release_id:
        return latest_ids, set()
    covering = set(latest_run_ids(runs.filter(releases=release_id), sbom_ids))
    candidates = list(
        AssessmentRun.objects.filter(id__in=[*latest_ids, *covering])
        .order_by("sbom_id", "plugin_name")
        .values_list("id", "sbom_id", "plugin_name")
    )
    covered = {(sbom_id, plugin) for run_id, sbom_id, plugin in candidates if run_id in covering}
    chosen = [
        run_id for run_id, sbom_id, plugin in candidates if run_id in covering or (sbom_id, plugin) not in covered
    ]
    return chosen, covering


def status_runs(run_ids: Any, order_by: str) -> list[Any]:
    """The runs with only what status readers use, so no findings list leaves the database.

    ``result`` is rebuilt from its ``summary`` and ``metadata`` slices. They are
    read from ``result`` itself rather than from the stored ``result_summary``
    and ``result_skipped`` columns: a run saved before those columns existed
    keeps its summary only in ``result`` until ``backfill_result_summaries`` runs.
    """
    from django.db.models import F

    from sbomify.apps.plugins.models import AssessmentRun

    runs = list(
        AssessmentRun.objects.filter(id__in=run_ids)
        .only("id", "sbom_id", "plugin_name", "category", "status", "completed_at")
        .annotate(summary_slice=F("result__summary"), metadata_slice=F("result__metadata"))
        .order_by(order_by)
    )
    for run in runs:
        run.result = {
            key: value
            for key, value in (("summary", run.summary_slice), ("metadata", run.metadata_slice))
            if value is not None
        }
    return runs


# What a reader can still resolve to, defined once.
#
# Readers take the newest completed security run per (SBOM, plugin)
# (latest_run_ids), and a release takes the newest such run that covers it
# (release_run_ids). So a completed run stops being readable once a newer
# completed run of the same SBOM and plugin covers every release it covers: it
# is then neither the newest run nor the newest for any of its releases. A run
# with no releases is superseded by any newer completed run, and a run that did
# not complete supersedes nothing, because no reader resolves to it.
#
# The finding projection keeps rows only for readable runs, the backfill and
# the legacy copy project only those, and the VEX re-apply rewrites only those.
# The result offload deliberately keys on the exact release set instead (see
# offload.current_run_ids): it governs the payload, which other readers rank
# differently.


def superseded_run_ids(runs: Any) -> set[Any]:
    """Which of ``runs`` a newer run of the same pair supersedes.

    ``runs`` yields ``(run_id, sbom_id, plugin_name, releases)`` for completed
    security runs, newest first (``-created_at`` then ``-id``), and must hold
    every such run of each pair it mentions. ``releases`` is a frozenset of
    release ids. Answered in one pass, without a query per run.
    """
    covering: dict[tuple[Any, str], list[frozenset[Any]]] = {}
    superseded: set[Any] = set()
    for run_id, sbom_id, plugin_name, releases in runs:
        newer = covering.setdefault((sbom_id, plugin_name), [])
        if any(releases <= other for other in newer):
            superseded.add(run_id)
        newer.append(releases)
    return superseded


def readable_runs(completed: QuerySet[Any]) -> tuple[list[Any], dict[Any, frozenset[Any]], set[Any]]:
    """Split ``completed`` into the runs a reader can resolve to and the ones it cannot.

    ``completed`` is a queryset of completed security runs covering whole
    (SBOM, plugin) pairs, typically every such run of some SBOMs. Returns the
    readable run ids newest first, the release set of every run, and the
    superseded ids. Two queries, over small columns only, so no result payload
    is read to decide.
    """
    identities = list(completed.order_by("-created_at", "-id").values_list("id", "sbom_id", "plugin_name"))
    releases = release_sets([run_id for run_id, _sbom_id, _plugin in identities])
    superseded = superseded_run_ids(
        (run_id, sbom_id, plugin_name, releases[run_id]) for run_id, sbom_id, plugin_name in identities
    )
    readable = [run_id for run_id, _sbom_id, _plugin in identities if run_id not in superseded]
    return readable, releases, superseded


def release_sets(run_ids: Any) -> dict[Any, frozenset[Any]]:
    """``{run id: frozenset of release ids}`` in one query; a run with no releases maps to an empty set."""
    from sbomify.apps.plugins.models import AssessmentRunRelease

    sets: dict[Any, set[Any]] = {run_id: set() for run_id in run_ids}
    for run_id, release_id in AssessmentRunRelease.objects.filter(assessment_run_id__in=list(sets)).values_list(
        "assessment_run_id", "release_id"
    ):
        sets[run_id].add(release_id)
    return {run_id: frozenset(releases) for run_id, releases in sets.items()}


def newer_than(run: Any, prefix: str = "") -> Any:
    """A Q for runs newer than ``run``: by ``created_at``, ties broken on id, the order every reader ranks in."""
    from django.db.models import Q

    return Q(**{f"{prefix}created_at__gt": run.created_at}) | Q(
        **{f"{prefix}created_at": run.created_at, f"{prefix}id__gt": run.id}
    )


def is_superseded(run: Any, releases: frozenset[Any] | None = None) -> bool:
    """Whether a newer completed security run of ``run``'s pair covers every release ``run`` covers.

    The single-run form of :func:`superseded_run_ids`, answered by the
    database. ``releases`` is ``run``'s release set when the caller already has
    it (a prefetch), which saves a query.
    """
    from django.db.models import Count, Q

    from sbomify.apps.plugins.models import AssessmentRun
    from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunStatus

    if releases is None:
        releases = release_sets([run.id])[run.id]
    newer = AssessmentRun.objects.filter(
        sbom_id=run.sbom_id,
        plugin_name=run.plugin_name,
        category=AssessmentCategory.SECURITY.value,
        status=RunStatus.COMPLETED.value,
    ).filter(newer_than(run))
    if releases:
        newer = newer.annotate(
            covered=Count("releases", filter=Q(releases__in=releases), distinct=True),
        ).filter(covered=len(releases))
    return newer.exists()
