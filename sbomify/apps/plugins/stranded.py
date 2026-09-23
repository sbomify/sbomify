"""Settle assessment runs that were left mid-flight.

``overall_status`` is pending while any run is pending, and the artifact page
renders that as "Processing". So one row left in ``PENDING`` spins the page for
good, and there was nothing to notice.

Three things strand a row. The ordinary one is that the work for a delayed
assessment is scheduled after its run row is written: ``sbom-verification``
creates its row and queues the task 120 seconds later, so a worker restart or
an evicted message inside that window leaves a row nobody is coming back for.
The other two are in the retry-exhaustion branch of ``run_assessment_task``,
which skips finalising when the run id did not survive, and swallows a
finalisation that fails. Both were already known: the comment there says
leaving the row pending "leaves the SBOM detail page spinning indefinitely".

None of those are worth chasing individually, because they share a shape: a row
in a non-terminal state with nothing scheduled against it. This sweeps by that
shape, so a fourth way of stranding a row is covered before anyone finds it.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db.models.functions import Coalesce
from django.utils import timezone

from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk.enums import RunStatus
from sbomify.logging import getLogger

logger = getLogger(__name__)

#: How long a run may sit in a non-terminal state before the sweep settles it.
#:
#: It has to clear the longest honest wait. A run that never started waits out
#: the 120 second delay on the verification enqueue. One that did has the 2, 5,
#: 10 and 15 minute RetryLaterError ladder and a five minute final attempt ahead
#: of it, about 37 minutes from its first start. An hour leaves room for a slow
#: external service without settling a run that is still legitimately waiting.
DEFAULT_STRANDED_AFTER = timedelta(hours=1)

_STRANDED_MESSAGE = (
    "This assessment never finished, so its result is unknown rather than failed. Re-run the plugin to try again."
)


def _stranded_after() -> timedelta:
    minutes = getattr(settings, "PLUGIN_STRANDED_RUN_MINUTES", None)
    return timedelta(minutes=minutes) if minutes else DEFAULT_STRANDED_AFTER


def sweep_stranded_runs() -> int:
    """Finalise every run stuck in a non-terminal state. Returns how many.

    Settles through ``finalize_stranded`` rather than writing status directly:
    it is idempotent and settles the row through a conditional update, so a
    worker that wakes up and completes the run honestly at the same moment wins
    rather than being clobbered.
    """
    from sbomify.apps.plugins.orchestrator import PluginOrchestrator

    cutoff = timezone.now() - _stranded_after()
    stale = (
        AssessmentRun.objects.filter(status__in=(RunStatus.PENDING.value, RunStatus.RUNNING.value))
        # Timed from the first attempt when there was one. A backed-up queue can
        # hold a row long before a worker picks it up, and the retry ladder
        # counts from that pickup, not from when the row was written.
        .annotate(since=Coalesce("started_at", "created_at"))
        .filter(since__lt=cutoff)
        .values_list("id", "plugin_name", "sbom_id")
    )

    orchestrator = PluginOrchestrator()
    settled = 0
    for run_id, plugin_name, sbom_id in stale.iterator():
        try:
            run = orchestrator.finalize_stranded(str(run_id), _STRANDED_MESSAGE)
            # It hands back the row even when a worker finished the run between
            # the query above and the update, so count only this sweep's marker.
            if run is not None and ((run.result or {}).get("metadata") or {}).get("stranded"):
                settled += 1
                logger.info(
                    "[PLUGIN] settled stranded run %s (%s) for SBOM %s",
                    run_id,
                    plugin_name,
                    sbom_id,
                )
        except Exception:
            # One row that refuses to settle must not strand the rest of the
            # sweep, which is the failure this whole module exists to end.
            logger.exception("[PLUGIN] could not settle stranded run %s", run_id)

    if settled:
        logger.warning("[PLUGIN] settled %d stranded assessment run(s)", settled)
    return settled
