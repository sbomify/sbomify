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
