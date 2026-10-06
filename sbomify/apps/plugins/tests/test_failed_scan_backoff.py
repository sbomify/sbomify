"""A scan that fails every hour should stop being retried every hour.

The scheduled sweep's dedup set is built from runs with
``status__in=["completed", "running", "pending"]``. ``failed`` is not in that
list, and that is deliberate: a failure is often transient, and making an SBOM
wait out a full cadence to find out would be the wrong default.

What was missing is the other half. A failure that keeps happening — a Dependency
Track project that cannot be polled, a server that rejects the upload every time
— never fills the skip window either, so the sweep re-enqueues it on every tick.
At ``skip_hours=1`` that is an hourly retry for as long as the artifact exists,
each attempt writing another run row and another error to the tracker.

``FAILURE_BACKOFF_HOURS`` starts at zero so the transient case keeps exactly the
cadence it has today, and escalates so a standing failure settles at one attempt
a day. These tests pin both halves, because a backoff that catches the first
failure would be a regression and one that never escalates would be a no-op.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.db.models import F
from django.utils import timezone

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.plugins.models import (
    AssessmentRun,
    RegisteredPlugin,
    RunStatus,
    TeamPluginSettings,
)
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason
from sbomify.apps.sboms.models import SBOM


@pytest.fixture
def scannable_sbom(sample_team_with_owner_member):
    """A paid team with one release-linked CycloneDX SBOM — the minimum the
    hourly sweep needs to consider an SBOM eligible."""
    team = sample_team_with_owner_member.team
    team.billing_plan = "business"
    team.save()

    RegisteredPlugin.objects.get_or_create(
        name="dependency-track",
        defaults={
            "display_name": "Dependency Track",
            "description": "DT",
            "category": AssessmentCategory.SECURITY.value,
            "version": "1.0.0",
            "plugin_class_path": "sbomify.apps.plugins.builtins.dependency_track.DependencyTrackPlugin",
            "is_enabled": True,
        },
    )
    settings, _ = TeamPluginSettings.objects.get_or_create(team=team)
    settings.enabled_plugins = ["dependency-track"]
    settings.save()

    product = Product.objects.create(name="p", team=team)
    component = Component.objects.create(name="c", team=team)
    product.components.add(component)
    sbom = SBOM.objects.create(name="s", component=component, format="cyclonedx", sbom_filename="s.json")
    ReleaseArtifact.objects.get_or_create(release=Release.get_or_create_latest_release(product), sbom=sbom)
    return sbom


#: Sentinel for a run row written before ``completed_at`` was recorded.
LEGACY_NO_COMPLETED_AT = object()


def _run_at_age(
    sbom: SBOM,
    *,
    hours_ago: float,
    status: str,
    settled_hours_ago: float | object | None = None,
    error_message: str | None = None,
    result: dict | None = None,
) -> AssessmentRun:
    """One settled DT run, backdated. ``created_at`` is ``auto_now_add``, so the
    age has to be written back after the insert.

    ``settled_hours_ago`` is when the run reached its verdict, which is what the
    backoff measures. It defaults to ``hours_ago`` -- a run that was picked up
    as soon as it was queued -- and the cases that matter are the ones where it
    does not, because the queue was backed up. Pass
    ``LEGACY_NO_COMPLETED_AT`` for a row written before the orchestrator
    recorded a completion time.

    ``result`` goes through ``save`` rather than a bulk update, so the
    denormalised ``result_summary`` column is populated the same way every
    production write populates it.
    """
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="dependency-track",
        plugin_version="1.0.0",
        plugin_config_hash="0" * 64,
        category=AssessmentCategory.SECURITY.value,
        run_reason=RunReason.SCHEDULED_REFRESH.value,
        status=status,
        result=result,
        error_message=error_message
        if error_message is not None
        else ("server closed the connection unexpectedly" if status == RunStatus.FAILED.value else ""),
    )
    now = timezone.now()
    fields: dict = {"created_at": now - timedelta(hours=hours_ago)}
    if settled_hours_ago is LEGACY_NO_COMPLETED_AT:
        fields["completed_at"] = None
    else:
        settled = hours_ago if settled_hours_ago is None else settled_hours_ago
        fields["completed_at"] = now - timedelta(hours=settled)  # type: ignore[arg-type]
    AssessmentRun.objects.filter(pk=run.pk).update(**fields)
    return run


def _failures(sbom: SBOM, ages_in_hours: list[float]) -> None:
    for age in ages_in_hours:
        _run_at_age(sbom, hours_ago=age, status=RunStatus.FAILED.value)


def _sweep(monkeypatch) -> list[dict]:
    """Run the hourly sweep, capturing what it would have enqueued."""
    from sbomify.apps.plugins.tasks import _is_paid_team, _run_scheduled_security_scans

    captured: list[dict] = []
    monkeypatch.setattr(
        "sbomify.apps.plugins.tasks.enqueue_assessment",
        lambda **kwargs: captured.append(kwargs),
    )
    _run_scheduled_security_scans(
        plugin_name="dependency-track",
        plan_filter=_is_paid_team,
        skip_hours=1,
        task_name="test_hourly_dt_scan",
        only_cyclonedx=True,
    )
    return captured


@pytest.mark.django_db
class TestOneFailureKeepsItsCadence:
    """The half that must not regress: a failure is usually transient."""

    def test_a_single_failure_is_retried_on_the_next_sweep(self, scannable_sbom, monkeypatch) -> None:
        _failures(scannable_sbom, [2])

        assert len(_sweep(monkeypatch)) == 1

    def test_a_failure_followed_by_a_success_is_not_a_streak(self, scannable_sbom, monkeypatch) -> None:
        """The streak is the run of failures ending at the latest run. A success
        after them settles the SBOM however many came before."""
        _failures(scannable_sbom, [9, 8, 7, 6, 5])
        _run_at_age(scannable_sbom, hours_ago=4, status=RunStatus.COMPLETED.value)

        assert len(_sweep(monkeypatch)) == 1


@pytest.mark.django_db
class TestAStreakBacksOff:
    def test_repeated_failures_stop_the_hourly_retry(self, scannable_sbom, monkeypatch) -> None:
        """The defect: five failures in a row, the newest an hour and a half ago,
        and the sweep queued a sixth."""
        _failures(scannable_sbom, [6, 5, 4, 3, 1.5])

        assert _sweep(monkeypatch) == []

    def test_the_wait_grows_with_the_streak(self, scannable_sbom, monkeypatch) -> None:
        """Two failures wait 2 hours, so at 3 hours old it is retried — the same
        SBOM with a longer streak would not be."""
        _failures(scannable_sbom, [4, 3])

        assert len(_sweep(monkeypatch)) == 1

    def test_two_failures_within_their_wait_are_held(self, scannable_sbom, monkeypatch) -> None:
        _failures(scannable_sbom, [3, 1.5])

        assert _sweep(monkeypatch) == []

    def test_it_is_retried_once_the_backoff_lapses(self, scannable_sbom, monkeypatch) -> None:
        """Backed off, not blocked. Whatever was broken server-side gets fixed
        without anyone intervening here, and the next sweep has to notice."""
        _failures(scannable_sbom, [40, 39, 38, 37, 25])

        captured = _sweep(monkeypatch)

        assert len(captured) == 1
        assert captured[0]["sbom_id"] == str(scannable_sbom.id)

    def test_the_wait_tops_out_rather_than_growing_without_end(self, scannable_sbom, monkeypatch) -> None:
        """A streak far past the ladder's length still waits a day, not a week:
        an SBOM must not become permanently unscannable because it failed often
        enough at some point."""

        # 61 failures in a row, the newest 20 hours ago: inside the ceiling.
        _failures(scannable_sbom, [float(hours) for hours in range(80, 19, -1)])

        assert _sweep(monkeypatch) == []

        # Age the whole streak by 6 hours. The newest failure is now 26 hours
        # old, and the SBOM is scanned again — the wait was the ceiling, not a
        # function of how long the streak is. Both timestamps move: the backoff
        # measures from the verdict, so ageing the row alone would not age the
        # failure.
        AssessmentRun.objects.filter(sbom=scannable_sbom).update(
            created_at=F("created_at") - timedelta(hours=6),
            completed_at=F("completed_at") - timedelta(hours=6),
        )

        assert len(_sweep(monkeypatch)) == 1


@pytest.mark.django_db
class TestInFlightRunsDoNotDecideTheStreak:
    """A pending or running run has neither failed nor succeeded. Counting it
    either way would make the streak depend on when the sweep happened to look."""

    def test_a_pending_retry_does_not_clear_the_backoff(self, scannable_sbom, monkeypatch) -> None:
        """Read as a success, an enqueued retry would reset the streak on every
        tick and the backoff could never fire at all."""
        _failures(scannable_sbom, [6, 5, 4, 3, 1.5])
        run = _run_at_age(scannable_sbom, hours_ago=1.2, status=RunStatus.PENDING.value)
        # Older than the skip window, so the window itself is not what holds it.
        AssessmentRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(hours=1.2))

        assert _sweep(monkeypatch) == []

    def test_a_pending_run_alone_is_not_a_failure(self, scannable_sbom, monkeypatch) -> None:
        """And it must not count towards a streak either. Held by the ordinary
        skip window if it is recent, not by this backoff."""
        _run_at_age(scannable_sbom, hours_ago=3, status=RunStatus.PENDING.value)

        assert len(_sweep(monkeypatch)) == 1


@pytest.mark.django_db
class TestTheBackoffIsScopedToItsPlugin:
    def test_another_plugins_failures_do_not_hold_this_one(self, scannable_sbom, monkeypatch) -> None:
        """Each scanner fails for its own reasons; OSV being down says nothing
        about whether Dependency Track can read this artifact."""
        for age in (6, 5, 4, 3, 1.5):
            run = AssessmentRun.objects.create(
                sbom=scannable_sbom,
                plugin_name="osv",
                plugin_version="1.0.0",
                plugin_config_hash="0" * 64,
                category=AssessmentCategory.SECURITY.value,
                run_reason=RunReason.SCHEDULED_REFRESH.value,
                status=RunStatus.FAILED.value,
            )
            AssessmentRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(hours=age))

        assert len(_sweep(monkeypatch)) == 1


@pytest.mark.django_db
class TestItDoesNotReadTheFatBlobToCountFailures:
    """``result`` runs to several MB and de-TOASTs whole. This sweep runs hourly
    across every SBOM of every paid workspace, so a streak count that projected
    the blob would be worse than the retries it prevents."""

    def test_no_query_selects_the_result_column(self, scannable_sbom) -> None:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from sbomify.apps.plugins.tasks import _failure_backed_off_sbom_ids

        _failures(scannable_sbom, [6, 5, 4, 3, 1.5])

        with CaptureQueriesContext(connection) as captured:
            backed_off = _failure_backed_off_sbom_ids("dependency-track", [str(scannable_sbom.id)], timezone.now())

        assert backed_off == {str(scannable_sbom.id)}
        # ``result``, not ``result_summary``: the small denormalised column is
        # exactly what this query is supposed to read instead of the blob.
        projects_the_blob = re.compile(r"\bresult\b(?!_)")
        assert [q["sql"] for q in captured.captured_queries if projects_the_blob.search(q["sql"])] == []


@pytest.mark.django_db
class TestTheWaitRunsFromTheFailureNotTheEnqueue:
    """Scheduled enqueueing writes the PENDING row; the worker settles it later.

    Those two times differ by however long the queue is backed up, and the
    backoff is about how long ago the scan *failed*. Measuring from
    ``created_at`` meant a run could fail seconds ago while its row was already
    older than the 24-hour ceiling, so the next sweep retried it at once -- the
    backoff was defeated by exactly the queue delay that makes a failing scan
    expensive to keep retrying.
    """

    def test_a_streak_settled_just_now_is_held_back(self, scannable_sbom, monkeypatch) -> None:
        # Rows queued days ago, every one of them failing in the last minutes.
        for age in (96.0, 95.0, 94.0, 93.0, 92.0):
            _run_at_age(
                scannable_sbom,
                hours_ago=age,
                status=RunStatus.FAILED.value,
                settled_hours_ago=0.05,
            )

        assert _sweep(monkeypatch) == []

    def test_the_same_rows_are_retried_once_the_failure_itself_ages_out(self, scannable_sbom, monkeypatch) -> None:
        """The mirror of the above: old rows *and* an old verdict do get retried."""
        for age in (96.0, 95.0, 94.0, 93.0, 92.0):
            _run_at_age(
                scannable_sbom,
                hours_ago=age,
                status=RunStatus.FAILED.value,
                settled_hours_ago=age,
            )

        assert len(_sweep(monkeypatch)) == 1

    def test_a_success_settled_after_an_earlier_failure_clears_the_streak(self, scannable_sbom, monkeypatch) -> None:
        """Ordering follows the verdict too, not the row.

        A success queued *before* a failure but settled *after* it clears the
        streak; ordering on ``created_at`` would have read it as the older run
        and left the SBOM backed off.
        """
        for age in (9.0, 8.0, 7.0, 6.0, 5.0):
            _run_at_age(scannable_sbom, hours_ago=age, status=RunStatus.FAILED.value, settled_hours_ago=4.0)
        _run_at_age(
            scannable_sbom,
            hours_ago=10.0,
            status=RunStatus.COMPLETED.value,
            settled_hours_ago=0.5,
        )

        assert len(_sweep(monkeypatch)) == 1

    def test_a_legacy_row_without_a_completion_time_falls_back_to_creation(self, scannable_sbom, monkeypatch) -> None:
        """Rows written before the orchestrator recorded ``completed_at``.

        They must keep behaving as they did rather than being read as
        infinitely old, which would exempt them from the backoff entirely.
        """
        for age in (0.5, 0.4, 0.3, 0.2, 0.1):
            _run_at_age(
                scannable_sbom,
                hours_ago=age,
                status=RunStatus.FAILED.value,
                settled_hours_ago=LEGACY_NO_COMPLETED_AT,
            )

        assert _sweep(monkeypatch) == []


@pytest.mark.django_db
class TestTheSweepStaysCheapAsTheTableGrows:
    """The sweep runs hourly, so what it costs per run is part of the feature.

    The cost has to be bounded by the plan, not by a filter applied after the
    database has already done the work. ``row_number() <= N`` over a window
    reads like a cap and is not one: Postgres computes the window across the
    whole partitioned set and discards afterwards, so the sort covered every
    terminal run of every SBOM in the history window and only the discarding
    was bounded. These pin the LATERAL that replaced it.
    """

    @staticmethod
    def _streak_sql_and_params(sbom_ids: list[str]) -> tuple[str, list]:
        from sbomify.apps.plugins.tasks import (
            _FAILURE_STREAK_SQL,
            FAILURE_BACKOFF_HOURS,
            FAILURE_HISTORY_HOURS,
        )

        return (
            _FAILURE_STREAK_SQL.format(table=AssessmentRun._meta.db_table),
            [
                sbom_ids,
                "dependency-track",
                timezone.now() - timedelta(hours=FAILURE_HISTORY_HOURS),
                len(FAILURE_BACKOFF_HOURS),
            ],
        )

    def test_each_sbom_is_one_bounded_index_probe(self, scannable_sbom) -> None:
        """What the plan must say: an index descent per SBOM, stopped by LIMIT.

        ``enable_seqscan = off`` asks the planner whether the index is *usable*
        here, which is the question -- on a small test table it would prefer a
        sequential scan whatever exists.
        """
        from django.db import connection

        if connection.vendor != "postgresql":
            pytest.skip("EXPLAIN plans and functional indexes are Postgres-specific here")

        # Enough history that the ordered index actually beats a bare sbom_id
        # scan plus a sort -- which is the whole reason it exists. With five
        # rows in the table the planner is right that it makes no difference.
        _failures(scannable_sbom, [float(hours) for hours in range(60, 20, -1)])
        sql, params = self._streak_sql_and_params([str(scannable_sbom.id)])

        with connection.cursor() as cursor:
            cursor.execute("ANALYZE plugins_assessment_runs")
            cursor.execute("SET enable_seqscan = off")
            cursor.execute("EXPLAIN " + sql, params)
            plan = "\n".join(row[0] for row in cursor.fetchall())
            cursor.execute("SET enable_seqscan = on")

        # The functional index: Coalesce(completed_at, created_at) is an
        # expression, so none of the plain-column indexes can serve either the
        # range or the ordering.
        assert "plugins_run_sbom_settled_idx" in plan, plan
        # The bound is the plan's.
        assert "Limit" in plan, plan
        # And not a window computed over everything and then thrown away.
        assert "WindowAgg" not in plan, plan
        # The index is partial on the same terminal-status predicate the query
        # filters by, and Postgres proves one from the other -- so the plan
        # carries no Filter at all and every row the descent reads is a row the
        # LIMIT counts. Without that the probe reads past whatever in-flight
        # runs sit above the newest settled one and the bound is approximate.
        assert "Filter:" not in plan, plan

    def test_a_long_history_is_not_a_long_read(self, scannable_sbom) -> None:
        """Forty runs on one SBOM, five rows back.

        The wait is ``FAILURE_BACKOFF_HOURS[min(count, len) - 1]``, so every
        streak at or past the ladder's length gets the same ceiling: a sixth
        consecutive failure cannot change the answer the fifth already gave.
        That is what makes the cap safe to push into the query.
        """
        from django.db import connection

        from sbomify.apps.plugins.tasks import FAILURE_BACKOFF_HOURS

        _failures(scannable_sbom, [float(hours) for hours in range(60, 20, -1)])
        assert AssessmentRun.objects.filter(sbom=scannable_sbom).count() == 40

        sql, params = self._streak_sql_and_params([str(scannable_sbom.id)])
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        assert len(rows) == len(FAILURE_BACKOFF_HOURS)

    def test_the_streak_is_only_asked_about_sboms_the_sweep_would_enqueue(self, scannable_sbom, monkeypatch) -> None:
        """The skip window runs first, and the probe never sees what it caught.

        This is what keeps the per-SBOM cost from being charged for every SBOM
        in the workspace: on a healthy fleet nearly everything is inside the
        ordinary skip window, and those never reach the backoff at all.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # Scanned ten minutes ago, so the ordinary skip window holds it.
        _run_at_age(scannable_sbom, hours_ago=0.16, status=RunStatus.COMPLETED.value)

        with CaptureQueriesContext(connection) as captured:
            assert _sweep(monkeypatch) == []

        assert [q["sql"] for q in captured.captured_queries if "CROSS JOIN LATERAL" in q["sql"]] == []

    def test_capping_the_scan_does_not_change_the_verdict(self, scannable_sbom, monkeypatch) -> None:
        """A streak longer than the ladder still backs off, at the ceiling."""
        _failures(scannable_sbom, [float(hours) for hours in range(60, 20, -1)])

        assert _sweep(monkeypatch) == []


@pytest.mark.django_db
class TestAFailureStoredAsACompletedRun:
    """A failure settled as a COMPLETED run carrying an error message.

    ``finalize_retry_exhausted`` writes this for a run that burnt through its
    RetryLaterError budget, and ``finalize_stranded`` for one nothing will come
    back for. Both are deliberate -- a settled run is what the compliance gates
    and the SBOM page need, rather than one stuck in PENDING -- so the backoff
    cannot key on ``status=failed`` alone.

    The *other* completed-but-failed shape, the one the scanner stores as an
    error finding with no error message at all, is in
    ``TestTheFailureTheScannerStoresAsAnErrorFinding`` below.
    """

    @staticmethod
    def _completed_with_error(sbom: SBOM, ages: list[float]) -> None:
        for age in ages:
            _run_at_age(
                sbom,
                hours_ago=age,
                status=RunStatus.COMPLETED.value,
                error_message="Retry budget exhausted: Dependency Track never answered",
            )

    def test_a_streak_of_them_backs_off(self, scannable_sbom, monkeypatch) -> None:
        self._completed_with_error(scannable_sbom, [5.0, 4.0, 3.0, 2.0, 1.0])

        assert _sweep(monkeypatch) == []

    def test_a_clean_completed_run_is_still_a_success(self, scannable_sbom, monkeypatch) -> None:
        """The discriminator must not turn every completed run into a failure."""
        _failures(scannable_sbom, [9.0, 8.0, 7.0, 6.0])
        _run_at_age(scannable_sbom, hours_ago=1.0, status=RunStatus.COMPLETED.value, error_message="")

        assert len(_sweep(monkeypatch)) == 1

    def test_the_two_shapes_count_as_one_streak(self, scannable_sbom, monkeypatch) -> None:
        """A run of failures does not reset because the storage shape changed."""
        _failures(scannable_sbom, [5.0, 4.0])
        self._completed_with_error(scannable_sbom, [3.0, 2.0, 1.0])

        assert _sweep(monkeypatch) == []

    def test_the_classifier_reads_every_marker_and_only_those(self) -> None:
        from sbomify.apps.plugins.tasks import _run_failed

        assert _run_failed(RunStatus.FAILED.value, "", None) is True
        assert _run_failed(RunStatus.FAILED.value, "boom", None) is True
        assert _run_failed(RunStatus.COMPLETED.value, "boom", None) is True
        assert _run_failed(RunStatus.COMPLETED.value, "", {"error_count": 1}) is True
        assert _run_failed(RunStatus.COMPLETED.value, "", {"error_count": 0}) is False
        assert _run_failed(RunStatus.COMPLETED.value, "", {"total_findings": 7}) is False
        assert _run_failed(RunStatus.COMPLETED.value, "", None) is False
        # ``bool`` is an ``int`` subclass; junk in the blob is not one error.
        assert _run_failed(RunStatus.COMPLETED.value, "", {"error_count": True}) is False
        assert _run_failed(RunStatus.COMPLETED.value, "", {"error_count": "1"}) is False


@pytest.mark.django_db
class TestTheFailureTheScannerStoresAsAnErrorFinding:
    """The shape the Dependency Track failures this backoff exists for actually take.

    A plugin that cannot reach, upload to or poll its server returns
    ``_create_error_result`` -- an ordinary result carrying one ``error``
    finding -- and the orchestrator stores it on its *success* path, writing
    ``status``, ``completed_at`` and ``result`` and nothing else. So the row has
    ``COMPLETED`` and an **empty** ``error_message``, and a classifier keyed on
    that column read the common case as a success and kept re-enqueueing it
    every hour.

    ``summary.error_count`` is the marker that is actually there, read off the
    denormalised ``result_summary`` column rather than the blob.
    """

    @staticmethod
    def _error_result() -> dict:
        """A real plugin-emitted error result, not a hand-written stand-in."""
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin

        return DependencyTrackPlugin()._create_error_result("DT upload failed: connection refused").to_dict()

    def _errored_runs(self, sbom: SBOM, ages: list[float]) -> None:
        for age in ages:
            _run_at_age(
                sbom,
                hours_ago=age,
                status=RunStatus.COMPLETED.value,
                error_message="",
                result=self._error_result(),
            )

    def test_the_orchestrator_really_does_store_it_with_no_error_message(self, scannable_sbom, monkeypatch) -> None:
        """The production path, driven end to end rather than described.

        This is what makes the rest of the class more than an assertion about a
        fixture: the team has Dependency Track enabled but no server to send
        the SBOM to, so the real plugin takes a real error path and the real
        orchestrator stores the result.
        """
        from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin
        from sbomify.apps.plugins.orchestrator import PluginOrchestrator

        monkeypatch.setattr(
            "sbomify.apps.plugins.orchestrator.get_sbom_data_bytes",
            lambda sbom_id: (
                scannable_sbom,
                b'{"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1, "components": []}',
            ),
        )

        run = PluginOrchestrator().run_assessment(
            sbom_id=str(scannable_sbom.id),
            plugin=DependencyTrackPlugin(),
            run_reason=RunReason.SCHEDULED_REFRESH,
        )
        run.refresh_from_db()

        # The gap this fix closes: settled, failed, and silent in the column a
        # failure was being looked for in.
        assert run.status == RunStatus.COMPLETED.value
        assert not run.error_message
        assert run.result["findings"][0]["status"] == "error"
        # And the marker that is there, in the small column, without the blob.
        assert run.result_summary["error_count"] == 1

        from sbomify.apps.plugins.tasks import _run_failed

        assert _run_failed(run.status, run.error_message, run.result_summary) is True

    def test_a_streak_of_them_backs_off(self, scannable_sbom, monkeypatch) -> None:
        """The defect Copilot caught: before the error-count marker was read,
        five of these in a row still queued a sixth."""
        self._errored_runs(scannable_sbom, [5.0, 4.0, 3.0, 2.0, 1.5])

        assert _sweep(monkeypatch) == []

    def test_a_scan_that_found_vulnerabilities_is_still_a_success(self, scannable_sbom, monkeypatch) -> None:
        """A result with findings but no errors must clear the streak.

        The scanners' success paths leave ``error_count`` at its default, so a
        busy SBOM with hundreds of CVEs is not mistaken for a broken one.
        """
        self._errored_runs(scannable_sbom, [9.0, 8.0, 7.0, 6.0])
        _run_at_age(
            scannable_sbom,
            hours_ago=1.0,
            status=RunStatus.COMPLETED.value,
            error_message="",
            result={
                "schema_version": "1.0",
                "summary": {"total_findings": 3, "error_count": 0, "by_severity": {"high": 3}},
                "findings": [],
            },
        )

        assert len(_sweep(monkeypatch)) == 1

    def test_the_three_shapes_count_as_one_streak(self, scannable_sbom, monkeypatch) -> None:
        """A run of failures does not reset because the storage shape changed.

        ``status=failed``, a settled COMPLETED row with ``error_message``, and a
        stored error result are the same event told three ways.
        """
        _failures(scannable_sbom, [5.0])
        _run_at_age(
            scannable_sbom,
            hours_ago=4.0,
            status=RunStatus.COMPLETED.value,
            error_message="Retry budget exhausted: Dependency Track never answered",
        )
        self._errored_runs(scannable_sbom, [3.0, 2.0, 1.5])

        assert _sweep(monkeypatch) == []

    def test_a_legacy_row_without_the_denormalised_column_is_not_read_as_a_failure(
        self, scannable_sbom, monkeypatch
    ) -> None:
        """Rows that predate ``result_summary`` read as unknown, not as failures.

        ``backfill_result_summaries`` fills them in; until it has, an unknown
        can only shorten a backoff, which is the safe direction.
        """
        self._errored_runs(scannable_sbom, [9.0, 8.0, 7.0, 6.0, 1.5])
        AssessmentRun.objects.filter(sbom=scannable_sbom).update(result_summary=None)

        assert len(_sweep(monkeypatch)) == 1
