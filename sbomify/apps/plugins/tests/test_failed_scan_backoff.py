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

from datetime import timedelta

import pytest
from django.utils import timezone

from sbomify.apps.core.models import Component, Product, Release, ReleaseArtifact
from sbomify.apps.plugins.models import (
    AssessmentRun,
    RegisteredPlugin,
    RunStatus,
    TeamPluginSettings,
)
from sbomify.apps.plugins.sdk.enums import AssessmentCategory
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


def _run_at_age(sbom: SBOM, *, hours_ago: float, status: str) -> AssessmentRun:
    """One settled DT run, backdated. ``created_at`` is ``auto_now_add``, so the
    age has to be written back after the insert."""
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="dependency-track",
        category=AssessmentCategory.SECURITY.value,
        status=status,
        error_message="server closed the connection unexpectedly" if status == RunStatus.FAILED.value else "",
    )
    AssessmentRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(hours=hours_ago))
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
        from django.db.models import F

        # 61 failures in a row, the newest 20 hours ago: inside the ceiling.
        _failures(scannable_sbom, [float(hours) for hours in range(80, 19, -1)])

        assert _sweep(monkeypatch) == []

        # Age the whole streak by 6 hours. The newest failure is now 26 hours
        # old, and the SBOM is scanned again — the wait was the ceiling, not a
        # function of how long the streak is.
        AssessmentRun.objects.filter(sbom=scannable_sbom).update(created_at=F("created_at") - timedelta(hours=6))

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
                category=AssessmentCategory.SECURITY.value,
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
        team_ids = {scannable_sbom.component.team_id}

        with CaptureQueriesContext(connection) as captured:
            backed_off = _failure_backed_off_sbom_ids("dependency-track", team_ids, timezone.now())

        assert backed_off == {str(scannable_sbom.id)}
        assert [q["sql"] for q in captured.captured_queries if '."result"' in q["sql"]] == []
