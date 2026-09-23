"""A run nobody is coming back for gets settled.

overall_status is pending while any run is pending, and the artifact page
renders that as "Processing". A run row is written before its work is queued,
so a lost message leaves a row with nothing scheduled against it and the page
spins for good. Nothing swept for it: the scheduled jobs on this queue are a
Dependency Track scan and a retention prune, and neither looks at run state.
"""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

import pytest
from django.utils import timezone

from sbomify.apps.core.models import Component
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk.enums import RunReason, RunStatus
from sbomify.apps.plugins.stranded import sweep_stranded_runs
from sbomify.apps.sboms.models import SBOM

pytestmark = pytest.mark.django_db


def _run(
    team, *, status: str, age: timedelta, started: timedelta | None = None, plugin: str = "sbom-verification"
) -> AssessmentRun:
    component = Component.objects.create(name=f"c-{plugin}-{age.total_seconds()}", team=team)
    sbom = SBOM.objects.create(
        component=component, name="s", version="1.0", format="cyclonedx", format_version="1.6", sbom_filename="s.json"
    )
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin,
        plugin_version="1.0.0",
        plugin_config_hash=sha256(plugin.encode()).hexdigest(),
        category="attestation",
        run_reason=RunReason.ON_UPLOAD.value,
        status=status,
    )
    # created_at is auto_now_add, so age it after the fact.
    AssessmentRun.objects.filter(pk=run.pk).update(
        created_at=timezone.now() - age,
        started_at=timezone.now() - started if started else None,
    )
    run.refresh_from_db()
    return run


class TestWhatTheSweepSettles:
    def test_a_run_pending_past_the_cutoff_is_settled(self, sample_team_with_owner_member) -> None:
        run = _run(sample_team_with_owner_member.team, status=RunStatus.PENDING.value, age=timedelta(hours=3))

        assert sweep_stranded_runs() == 1

        run.refresh_from_db()
        assert run.status not in (RunStatus.PENDING.value, RunStatus.RUNNING.value)
        assert run.completed_at is not None

    def test_a_run_still_inside_the_retry_ladder_is_left_alone(self, sample_team_with_owner_member) -> None:
        """The honest wait is the 120 second delay plus the 2, 5, 10 and 15
        minute ladder. A run ten minutes in may yet complete on its own."""
        run = _run(sample_team_with_owner_member.team, status=RunStatus.PENDING.value, age=timedelta(minutes=10))

        assert sweep_stranded_runs() == 0

        run.refresh_from_db()
        assert run.status == RunStatus.PENDING.value

    def test_a_run_stuck_running_is_settled_too(self, sample_team_with_owner_member) -> None:
        """A worker that died mid-assessment leaves RUNNING rather than
        PENDING, and spins the page just the same."""
        run = _run(sample_team_with_owner_member.team, status=RunStatus.RUNNING.value, age=timedelta(hours=3))

        assert sweep_stranded_runs() == 1

        run.refresh_from_db()
        assert run.status not in (RunStatus.PENDING.value, RunStatus.RUNNING.value)

    @pytest.mark.parametrize("status", [RunStatus.PENDING.value, RunStatus.RUNNING.value])
    def test_the_clock_starts_at_the_first_attempt(self, sample_team_with_owner_member, status: str) -> None:
        """A backed-up queue can hold a row for hours before a worker picks it
        up. Timed from when the row was written, a run picked up ten minutes
        ago would be settled while it runs or waits on its next retry."""
        run = _run(
            sample_team_with_owner_member.team, status=status, age=timedelta(hours=3), started=timedelta(minutes=10)
        )

        assert sweep_stranded_runs() == 0

        run.refresh_from_db()
        assert run.status == status

    def test_a_run_its_worker_finished_first_is_not_counted(self, sample_team_with_owner_member, mocker) -> None:
        """finalize_stranded hands back the row even when a worker completed it
        between the sweep's query and the update, so only a row carrying the
        sweep's own marker counts as settled."""
        run = _run(sample_team_with_owner_member.team, status=RunStatus.PENDING.value, age=timedelta(hours=3))
        run.status = RunStatus.COMPLETED.value
        run.result = {"summary": {"total_findings": 0}, "findings": [], "metadata": {}}
        mocker.patch("sbomify.apps.plugins.orchestrator.PluginOrchestrator.finalize_stranded", return_value=run)

        assert sweep_stranded_runs() == 0

    def test_a_completed_run_is_not_touched(self, sample_team_with_owner_member) -> None:
        run = _run(sample_team_with_owner_member.team, status=RunStatus.COMPLETED.value, age=timedelta(hours=3))
        before = run.status

        assert sweep_stranded_runs() == 0

        run.refresh_from_db()
        assert run.status == before

    def test_the_sweep_is_idempotent(self, sample_team_with_owner_member) -> None:
        """It runs every twenty minutes, so a second pass over the same row
        must settle nothing rather than rewrite it."""
        _run(sample_team_with_owner_member.team, status=RunStatus.PENDING.value, age=timedelta(hours=3))

        assert sweep_stranded_runs() == 1
        assert sweep_stranded_runs() == 0


class TestWhatTheArtifactPageSeesAfterwards:
    def test_the_settled_run_stops_reading_as_pending(self, sample_team_with_owner_member) -> None:
        """The point of the sweep. While any run is pending the overall status
        is pending, which the page renders as "Processing"."""
        run = _run(sample_team_with_owner_member.team, status=RunStatus.PENDING.value, age=timedelta(hours=3))

        sweep_stranded_runs()

        run.refresh_from_db()
        assert run.status == RunStatus.COMPLETED.value
        assert run.result, "a settled run needs a result, or the page has nothing to show"

    def test_the_settled_run_says_it_never_finished(self, sample_team_with_owner_member) -> None:
        """Not that a retry budget ran out. A stranded run usually never
        started, so it spent no retries."""
        run = _run(sample_team_with_owner_member.team, status=RunStatus.PENDING.value, age=timedelta(hours=3))

        sweep_stranded_runs()

        run.refresh_from_db()
        finding = run.result["findings"][0]
        assert finding["id"] == "sbom-verification:stranded"
        assert finding["title"] == "Assessment Never Completed"
        assert run.result["metadata"] == {"stranded": True}
        assert "Retry budget" not in (run.error_message or "")
