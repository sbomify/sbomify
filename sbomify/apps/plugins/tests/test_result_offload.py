"""Demoting a superseded result payload to object storage must lose nothing.

The row, its summary columns and its normalised findings stay in Postgres; only
the payload moves. Three properties carry the whole design and each has a test
here:

* **A current run is never demoted**, where current means per (sbom, plugin,
  release set) — one SBOM in two releases has a live run for each.
* **A payload is stored before the row is changed**, and the key and the NULL
  land in one UPDATE, so no row can be observed holding neither.
* **The summary columns survive.** They are recomputed from the payload while it
  is still in hand, so a legacy row whose columns were never backfilled comes
  out with counts rather than losing them.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from sbomify.apps.core.models import Component, Product, Release
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.offload import (
    DEFAULT_OFFLOAD_AFTER_DAYS,
    demotable_run_ids,
    offload_assessment_results,
)
from sbomify.apps.plugins.result_store import (
    RESULT_PREFIX,
    ResultObjectMissing,
    load_result,
    object_key_for,
    serialise_result,
)
from sbomify.apps.sboms.models import SBOM, ProductComponent


class FakeBucket:
    """An in-memory stand-in for the SBOMS bucket, with the methods used here."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts = 0

    def upload_data_as_file(self, bucket: str, key: str, data: bytes) -> None:
        self.puts += 1
        self.objects[key] = data

    def get_file_data(self, bucket: str, key: str) -> bytes | None:
        return self.objects.get(key)

    def object_exists(self, bucket: str, key: str) -> bool:
        return key in self.objects

    def list_cached_aggregates(self, prefix: str) -> list[str]:
        return [key for key in self.objects if key.startswith(prefix)]

    def delete_object(self, bucket: str, key: str) -> None:
        self.objects.pop(key, None)


@pytest.fixture
def bucket(monkeypatch) -> FakeBucket:
    fake = FakeBucket()
    monkeypatch.setattr("sbomify.apps.plugins.result_store._client", lambda: fake)
    monkeypatch.setattr("sbomify.apps.plugins.result_store._bucket", lambda: "test-bucket")
    return fake


def _result(total: int = 2) -> dict[str, Any]:
    return {
        "plugin_name": "osv",
        "plugin_version": "1.0.0",
        "category": "security",
        "assessed_at": timezone.now().isoformat(),
        "summary": {"total_findings": total, "by_severity": {"high": total}},
        "findings": [
            {
                "id": f"CVE-2026-{index}",
                # title and description are required by FindingSchema, so a
                # fixture without them serialises as result=None and would hide
                # whether the payload was loaded at all.
                "title": f"CVE-2026-{index}",
                "description": "a finding",
                "severity": "high",
                "component": {"name": "foo", "version": "1"},
            }
            for index in range(total)
        ],
    }


def _run(
    sbom: SBOM,
    plugin: str = "osv",
    *,
    days_ago: int,
    result: dict[str, Any] | None = None,
    status: str = "completed",
) -> AssessmentRun:
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin,
        plugin_version="1.0.0",
        plugin_config_hash="0" * 64,
        category="security",
        run_reason="scheduled_refresh",
        status=status,
        result=_result() if result is None else result,
    )
    AssessmentRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
    run.refresh_from_db()
    return run


@pytest.fixture
def sbom(sample_team_with_owner_member) -> SBOM:
    component = Component.objects.create(name="c", team=sample_team_with_owner_member.team)
    return SBOM.objects.create(
        name="app",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="a.json",
        component=component,
    )


@pytest.mark.django_db
class TestWhatIsSafeToDemote:
    def test_the_current_run_is_never_demotable(self, sbom):
        """However old it is. It is the answer every reader resolves to, and a
        frozen release keeps its posture from its last scan indefinitely."""
        only = _run(sbom, days_ago=900)

        assert demotable_run_ids(older_than_days=0) == []
        assert only.id not in demotable_run_ids(older_than_days=0)

    def test_a_superseded_run_is_demotable(self, sbom):
        current = _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800)

        doomed = demotable_run_ids()

        assert doomed == [superseded.id]
        assert current.id not in doomed

    def test_the_age_floor_holds_recent_runs_back(self, sbom):
        _run(sbom, days_ago=1)
        recent_superseded = _run(sbom, days_ago=5)

        assert demotable_run_ids() == []
        # …and is a parameter, not a law.
        assert demotable_run_ids(older_than_days=2) == [recent_superseded.id]

    def test_each_provider_keeps_its_own_current_run(self, sbom):
        osv_current = _run(sbom, "osv", days_ago=400)
        dt_current = _run(sbom, "dependency-track", days_ago=500)
        osv_old = _run(sbom, "osv", days_ago=800)
        dt_old = _run(sbom, "dependency-track", days_ago=900)

        doomed = set(demotable_run_ids())

        assert doomed == {osv_old.id, dt_old.id}
        assert osv_current.id not in doomed
        assert dt_current.id not in doomed

    def test_a_newer_failed_run_does_not_unseat_the_last_completed_one(self, sbom):
        """The findings readers ask for the newest completed run, and a failed
        run can carry a synthesised result, so it ranks as a payload too."""
        completed = _run(sbom, days_ago=800)
        older = _run(sbom, days_ago=900)
        _run(sbom, days_ago=1, status="failed")

        assert demotable_run_ids() == [older.id]
        assert completed.id not in demotable_run_ids()

    def test_a_run_with_no_payload_is_not_a_candidate(self, sbom):
        _run(sbom, days_ago=400)
        pending = AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="osv",
            plugin_version="1.0.0",
            plugin_config_hash="0" * 64,
            category="security",
            run_reason="scheduled_refresh",
            status="pending",
        )
        AssessmentRun.objects.filter(pk=pending.pk).update(created_at=timezone.now() - timedelta(days=800))

        assert pending.id not in demotable_run_ids()

    def test_the_default_floor_is_past_the_furthest_reader(self, sbom):
        """The drill-down accepts a 365-day window and renders findings from the
        payload, so the default floor has to clear it. A test rather than a
        comment, because lowering it silently is the way this breaks."""
        assert DEFAULT_OFFLOAD_AFTER_DAYS > 365


@pytest.mark.django_db
class TestReleaseContextsAreBothCurrent:
    """One SBOM in two releases has a live run for each, because the VEX
    re-annotation is release-aware. Keyed on (sbom, plugin) alone the older one
    looks superseded, and demoting it takes the payload of a row a VEX upload is
    still expected to rewrite."""

    def test_the_older_release_context_is_protected(self, sbom):
        product = Product.objects.create(name="p", team=sbom.component.team)
        ProductComponent.objects.create(product=product, component=sbom.component)
        v1 = Release.objects.create(product=product, name="v1")
        v2 = Release.objects.create(product=product, name="v2")

        older = _run(sbom, days_ago=800)
        older.releases.add(v1)
        newer = _run(sbom, days_ago=400)
        newer.releases.add(v2)

        doomed = demotable_run_ids()

        assert older.id not in doomed
        assert newer.id not in doomed

    def test_two_runs_in_the_same_release_still_rank(self, sbom):
        """The release set widens the key; it does not disable the ranking."""
        product = Product.objects.create(name="p2", team=sbom.component.team)
        ProductComponent.objects.create(product=product, component=sbom.component)
        v1 = Release.objects.create(product=product, name="v1")

        current = _run(sbom, days_ago=400)
        current.releases.add(v1)
        superseded = _run(sbom, days_ago=800)
        superseded.releases.add(v1)

        assert demotable_run_ids() == [superseded.id]


@pytest.mark.django_db
class TestTheMove:
    def test_the_payload_lands_in_storage_and_the_row_points_at_it(self, sbom, bucket):
        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800)
        payload = superseded.result

        assert offload_assessment_results() == 1

        superseded.refresh_from_db()
        assert superseded.result is None
        assert superseded.result_object_key == object_key_for(superseded.id, serialise_result(payload))
        assert superseded.result_object_key.startswith(f"{RESULT_PREFIX}{superseded.id}/")
        assert json.loads(bucket.objects[superseded.result_object_key]) == payload

    def test_it_reads_back_byte_identical(self, sbom, bucket):
        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800)
        payload = superseded.result

        offload_assessment_results()
        superseded.refresh_from_db()

        assert load_result(superseded) == payload

    def test_the_summary_columns_survive(self, sbom, bucket):
        """They are what every dashboard reads, and the only copy of the counts
        once the payload has moved."""
        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800, result=_result(total=7))

        offload_assessment_results()
        superseded.refresh_from_db()

        assert superseded.result is None
        assert superseded.result_summary == {"total_findings": 7, "by_severity": {"high": 7}}

    def test_a_legacy_row_with_no_summary_gains_one(self, sbom, bucket):
        """A row written before the summary columns existed has them NULL.
        Nulling its payload without filling them first would lose its counts for
        good, so the sweep recomputes them from the payload it is holding rather
        than trusting a backfill to have run first."""
        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800, result=_result(total=3))
        # Simulate the legacy state: payload present, derived columns never set.
        AssessmentRun.objects.filter(pk=superseded.pk).update(result_summary=None, result_skipped=None)

        offload_assessment_results()
        superseded.refresh_from_db()

        assert superseded.result_summary == {"total_findings": 3, "by_severity": {"high": 3}}

    def test_a_dry_run_stores_nothing_and_changes_nothing(self, sbom, bucket):
        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800)

        assert offload_assessment_results(dry_run=True) == 1

        superseded.refresh_from_db()
        assert superseded.result is not None
        assert superseded.result_object_key == ""
        assert bucket.objects == {}

    def test_running_twice_stores_once_and_moves_once(self, sbom, bucket):
        """Keys are content hashes, so the sweep is safe to interrupt and re-run:
        the second pass finds nothing left to do and uploads nothing."""
        _run(sbom, days_ago=400)
        _run(sbom, days_ago=800)

        assert offload_assessment_results() == 1
        puts_after_first = bucket.puts

        assert offload_assessment_results() == 0
        assert bucket.puts == puts_after_first

    def test_batching_does_not_change_the_outcome(self, sbom, bucket):
        _run(sbom, days_ago=400)
        for day in range(500, 900, 50):
            _run(sbom, days_ago=day)

        moved = offload_assessment_results(batch_size=2)

        assert moved == 8
        assert AssessmentRun.objects.filter(result__isnull=False).count() == 1

    def test_the_limit_bounds_one_pass(self, sbom, bucket):
        _run(sbom, days_ago=400)
        for day in range(500, 900, 50):
            _run(sbom, days_ago=day)

        assert offload_assessment_results(limit=3) <= 3
        assert AssessmentRun.objects.exclude(result_object_key="").count() <= 3

    def test_the_sweep_holds_one_page_of_candidates_at_a_time(self, sbom, bucket, mocker):
        """A first pass over a large table must not load every candidate up
        front, so each page is ranked on its own SBOMs and plugins."""
        from sbomify.apps.plugins import offload

        current = _run(sbom, days_ago=400)
        older = [_run(sbom, days_ago=day) for day in (500, 600, 700)]
        ranked = mocker.spy(offload, "current_run_ids")

        assert offload_assessment_results(batch_size=2) == len(older)

        assert ranked.call_count == 2
        assert AssessmentRun.objects.get(pk=current.pk).result_object_key == ""
        assert all(AssessmentRun.objects.get(pk=run.pk).result_object_key for run in older)

    def test_a_dry_run_counts_across_pages(self, sbom, bucket):
        _run(sbom, days_ago=400)
        for day in (500, 600, 700):
            _run(sbom, days_ago=day)

        assert offload_assessment_results(batch_size=2, dry_run=True) == 3
        assert bucket.puts == 0


@pytest.mark.django_db
class TestAMissingPayloadIsNotAnEmptyOne:
    """The failure this design must never have: a run whose payload cannot be
    read showing up as a run that found nothing. `result_summary` stays in the
    database precisely so the counts do not depend on the object."""

    def test_load_result_raises_rather_than_returning_empty(self, sbom, bucket):
        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800)
        offload_assessment_results()
        superseded.refresh_from_db()

        bucket.objects.clear()

        with pytest.raises(ResultObjectMissing):
            load_result(superseded)

    def test_a_run_that_never_had_a_payload_reads_as_none(self, sbom, bucket):
        """Absent and unreadable are different answers and must stay apart."""
        pending = AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="osv",
            plugin_version="1.0.0",
            plugin_config_hash="0" * 64,
            category="security",
            run_reason="scheduled_refresh",
            status="pending",
        )

        assert load_result(pending) is None

    def test_the_counts_still_read_without_the_object(self, sbom, bucket):
        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800, result=_result(total=5))
        offload_assessment_results()
        bucket.objects.clear()
        superseded.refresh_from_db()

        from sbomify.apps.vulnerability_scanning.utils import extract_severity_counts, reconstruct_result_summary

        assert extract_severity_counts(reconstruct_result_summary(superseded))["total"] == 5


@pytest.mark.django_db
class TestTheApiDegradesRatherThanFailing:
    def test_an_unreadable_payload_serialises_without_it(self, sbom, bucket, rf, monkeypatch):
        """One bad object must not blank the assessments response for the SBOM,
        the same treatment a result failing schema validation already gets."""
        from sbomify.apps.plugins.apis import get_sbom_assessments

        current = _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800)
        offload_assessment_results()
        bucket.objects.clear()

        monkeypatch.setattr("sbomify.apps.plugins.apis._readable_sbom", lambda request, sbom_id: sbom)
        request = rf.get("/")
        request.user = None
        response = get_sbom_assessments(request, sbom.id)

        by_id = {run.id: run for run in response.all_runs}
        assert by_id[str(superseded.id)].result is None
        assert by_id[str(current.id)].result is not None

    def test_an_offloaded_payload_is_served_from_storage(self, sbom, bucket, rf, monkeypatch):
        from sbomify.apps.plugins.apis import get_sbom_assessments

        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800, result=_result(total=2))
        offload_assessment_results()

        monkeypatch.setattr("sbomify.apps.plugins.apis._readable_sbom", lambda request, sbom_id: sbom)
        request = rf.get("/")
        request.user = None
        response = get_sbom_assessments(request, sbom.id)

        served = {run.id: run for run in response.all_runs}[str(superseded.id)]
        assert served.result is not None
        assert len(served.result.findings) == 2


@pytest.mark.django_db
class TestFindingRowsOutliveTheMove:
    """``backfill_findings`` re-projects every completed security run. An
    offloaded run's payload is in storage, not in ``result``, and reading the
    empty column as "no findings" would delete the run's rows."""

    def test_reprojecting_an_offloaded_run_keeps_its_rows(self, sbom, bucket):
        from sbomify.apps.vulnerability_scanning.findings import sync_findings
        from sbomify.apps.vulnerability_scanning.models import Finding

        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800)
        sync_findings(superseded, [])
        projected = set(Finding.objects.filter(run=superseded).values_list("advisory_id", flat=True))
        assert offload_assessment_results() == 1
        superseded.refresh_from_db()

        sync_findings(superseded, [])

        assert (
            projected and set(Finding.objects.filter(run=superseded).values_list("advisory_id", flat=True)) == projected
        )

    def test_an_unreadable_payload_leaves_the_rows_alone(self, sbom, bucket):
        """A missing object is not an empty result: the re-projection fails
        loudly and the rows it would have rewritten stay."""
        from sbomify.apps.vulnerability_scanning.findings import sync_findings
        from sbomify.apps.vulnerability_scanning.models import Finding

        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800)
        sync_findings(superseded, [])
        assert offload_assessment_results() == 1
        superseded.refresh_from_db()
        bucket.objects.clear()

        with pytest.raises(ResultObjectMissing):
            sync_findings(superseded, [])

        assert Finding.objects.filter(run=superseded).count() == 2


@pytest.mark.django_db
class TestRetentionReclaimsTheStoredPayload:
    def test_pruning_an_offloaded_run_deletes_its_objects(self, sbom, bucket):
        """Retention prunes runs beyond the per-plugin quota. The row is the only
        pointer to an offloaded payload, so deleting it must take the objects too
        or they stay in the bucket for good."""
        from sbomify.apps.plugins.retention import prune_assessment_runs

        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800)
        assert offload_assessment_results() == 1

        assert prune_assessment_runs(keep_per_plugin=1, min_age_days=0) == 1

        assert not AssessmentRun.objects.filter(pk=superseded.pk).exists()
        assert [key for key in bucket.objects if key.startswith(f"{RESULT_PREFIX}{superseded.id}/")] == []

    @pytest.mark.django_db(transaction=True)
    def test_an_offload_landing_mid_prune_still_has_its_objects_deleted(self, sbom, bucket):
        """An offload that commits its key after the batch read which rows hold
        one, but before the delete, would leave its object behind for good.
        Here it holds its row lock while the prune starts, as the sweep does
        from reading the payload to committing the key."""
        import threading

        from django.db import connection, transaction

        from sbomify.apps.plugins.retention import prune_assessment_runs

        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800)
        late_key = f"{RESULT_PREFIX}{superseded.id}/late.json"
        locked = threading.Event()

        def offload_commits_late() -> None:
            try:
                with transaction.atomic():
                    AssessmentRun.objects.filter(pk=superseded.pk).update(result=None, result_object_key=late_key)
                    bucket.objects[late_key] = b"{}"
                    locked.set()
                    # Held long enough for the prune to have read its batch.
                    threading.Event().wait(1)
            finally:
                connection.close()

        worker = threading.Thread(target=offload_commits_late)
        worker.start()
        assert locked.wait(5)

        assert prune_assessment_runs(keep_per_plugin=1, min_age_days=0) == 1
        worker.join(5)

        assert not AssessmentRun.objects.filter(pk=superseded.pk).exists()
        assert late_key not in bucket.objects

    def test_objects_a_failed_delete_left_behind_are_collected(self, sbom, bucket):
        """The row commits before its objects go, so an object store error in
        between leaves them pointing at nothing, and the retry can no longer
        find the row. The orphan sweep finds them by their run id instead."""
        from sbomify.apps.plugins.result_store import delete_orphaned_result_objects
        from sbomify.apps.plugins.retention import prune_assessment_runs

        _run(sbom, days_ago=400)
        kept = _run(sbom, days_ago=800)
        pruned = _run(sbom, days_ago=900)
        assert offload_assessment_results() == 2

        def unreachable(bucket_name: str, key: str) -> None:
            raise ConnectionError("object store unreachable")

        bucket.delete_object = unreachable  # type: ignore[method-assign]
        with pytest.raises(ConnectionError):
            prune_assessment_runs(keep_per_plugin=2, min_age_days=0)
        del bucket.delete_object
        assert not AssessmentRun.objects.filter(pk=pruned.pk).exists()

        assert delete_orphaned_result_objects() == 1

        assert not [key for key in bucket.objects if key.startswith(f"{RESULT_PREFIX}{pruned.id}/")]
        assert [key for key in bucket.objects if key.startswith(f"{RESULT_PREFIX}{kept.id}/")]

    def test_the_daily_task_collects_orphans_before_it_prunes(self, mocker):
        """First, so the retry of a run that failed mid-delete collects what
        that attempt left behind."""
        from sbomify.apps.plugins.tasks import prune_assessment_runs_task

        calls = mocker.Mock()
        calls.orphans.return_value = calls.prune.return_value = 0
        mocker.patch("sbomify.apps.plugins.result_store.delete_orphaned_result_objects", calls.orphans)
        mocker.patch("sbomify.apps.plugins.retention.prune_assessment_runs", calls.prune)

        prune_assessment_runs_task.fn()

        assert [name for name, *_ in calls.mock_calls] == ["orphans", "prune"]


@pytest.mark.django_db
class TestTheRunFindingsCardReadsStorage:
    """The card on the artifact page pages one run's findings out of ``result``
    in SQL. An offloaded run holds nothing there, so read the old way its card
    would list no findings at all, the one answer an unreachable payload must
    never give."""

    def _page(self, run, sbom, rf, monkeypatch):
        from sbomify.apps.plugins.services.run_findings import build_run_findings_page

        monkeypatch.setattr("sbomify.apps.plugins.apis._readable_sbom", lambda request, sbom_id: sbom)
        return build_run_findings_page(rf.get("/"), str(run.id))

    def test_an_offloaded_run_pages_the_same_findings(self, sbom, bucket, rf, monkeypatch):
        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800)
        before = self._page(superseded, sbom, rf, monkeypatch)
        assert offload_assessment_results() == 1
        superseded.refresh_from_db()

        after = self._page(superseded, sbom, rf, monkeypatch)

        assert before.ok and len(before.value.findings) == 2
        assert after.ok and after.value.panel == before.value.panel

    def test_an_unreadable_payload_is_an_error_not_an_empty_page(self, sbom, bucket, rf, monkeypatch):
        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800)
        assert offload_assessment_results() == 1
        superseded.refresh_from_db()
        bucket.objects.clear()

        page = self._page(superseded, sbom, rf, monkeypatch)

        assert not page.ok and page.status_code == 503


@pytest.mark.django_db
class TestVexReachesAnOffloadedRun:
    """A VEX uploaded after a scan is re-applied to the component's completed
    runs. Read from the column, an offloaded run's payload is not there, so the
    run would be skipped and keep a disposition the new VEX changed."""

    def test_the_rewrite_lands_as_a_new_revision(self, sbom, bucket, monkeypatch):
        from sbomify.apps.vulnerability_scanning import vex
        from sbomify.apps.vulnerability_scanning.findings import sync_findings
        from sbomify.apps.vulnerability_scanning.models import Finding

        payload = _result()
        for finding in payload["findings"]:
            finding["component"]["ecosystem"] = "pypi"
        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800, result=payload)
        sync_findings(superseded, [])
        assert offload_assessment_results() == 1
        superseded.refresh_from_db()
        first_key = superseded.result_object_key

        statement = {
            "ids": {"cve-2026-0"},
            "packages": {("pypi", "foo", "1")},
            "state": "not_affected",
            "justification": "code_not_reachable",
            "product_scoped": False,
            "source": "manual",
        }
        monkeypatch.setattr(vex, "_statements_for_release_context", lambda component_id, release_ids: [statement])
        monkeypatch.setattr(vex, "_embedded_statements", lambda sbom: [])

        vex.reannotate_component_runs(sbom.component_id)

        superseded.refresh_from_db()
        assert superseded.result is None
        assert superseded.result_object_key not in ("", first_key)
        # Content-addressed: the earlier revision stays where it was.
        assert first_key in bucket.objects
        assert Finding.objects.get(run=superseded, advisory_id="CVE-2026-0").vex_suppressed is True
        assert Finding.objects.get(run=superseded, advisory_id="CVE-2026-1").vex_suppressed is False

    def test_an_unreadable_payload_does_not_stop_the_rest(self, sbom, bucket, monkeypatch):
        from sbomify.apps.vulnerability_scanning import vex

        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800)
        assert offload_assessment_results() == 1
        bucket.objects.clear()
        monkeypatch.setattr(vex, "_statements_for_release_context", lambda component_id, release_ids: [])
        monkeypatch.setattr(vex, "_embedded_statements", lambda sbom: [])

        vex.reannotate_component_runs(sbom.component_id)

        superseded.refresh_from_db()
        assert superseded.result is None and superseded.result_object_key

    def test_a_row_that_is_gone_stores_nothing(self, sbom, bucket):
        """The row is locked before anything is stored, so a run retention has
        already taken gets no object nothing would ever point at."""
        from sbomify.apps.plugins.result_store import save_result

        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800)
        assert offload_assessment_results() == 1
        superseded.refresh_from_db()
        AssessmentRun.objects.filter(pk=superseded.pk).delete()
        puts = bucket.puts

        save_result(superseded, _result(total=1))

        assert bucket.puts == puts

    @pytest.mark.django_db(transaction=True)
    def test_an_offload_landing_mid_rewrite_does_not_split_the_payload(self, sbom, bucket, monkeypatch):
        """The re-apply reads a run, then writes it. An offload committing in
        between, as the sweep does while it holds the row lock, must not leave
        the rewrite inline beside a key to the payload it replaced: readers
        would take the inline copy and no later sweep would move it."""
        import threading

        from django.db import connection, transaction

        from sbomify.apps.plugins.result_store import object_key_for
        from sbomify.apps.vulnerability_scanning import vex

        payload = _result()
        for finding in payload["findings"]:
            finding["component"]["ecosystem"] = "pypi"
        _run(sbom, days_ago=400)
        superseded = _run(sbom, days_ago=800, result=payload)
        old_bytes = serialise_result(superseded.result)
        old_key = object_key_for(superseded.id, old_bytes)
        statement = {
            "ids": {"cve-2026-0"},
            "packages": {("pypi", "foo", "1")},
            "state": "not_affected",
            "justification": "code_not_reachable",
            "product_scoped": False,
            "source": "manual",
        }
        monkeypatch.setattr(vex, "_statements_for_release_context", lambda component_id, release_ids: [statement])
        monkeypatch.setattr(vex, "_embedded_statements", lambda sbom: [])
        locked = threading.Event()

        def offload_commits_late() -> None:
            try:
                with transaction.atomic():
                    bucket.objects[old_key] = old_bytes
                    AssessmentRun.objects.filter(pk=superseded.pk).update(result=None, result_object_key=old_key)
                    locked.set()
                    # Held long enough for the re-apply to have read the run.
                    threading.Event().wait(1)
            finally:
                connection.close()

        worker = threading.Thread(target=offload_commits_late)
        worker.start()
        assert locked.wait(5)

        vex.reannotate_component_runs(sbom.component_id)
        worker.join(5)

        superseded.refresh_from_db()
        assert superseded.result is None
        assert superseded.result_object_key not in ("", old_key)
        rewritten = load_result(superseded)
        assert next(f for f in rewritten["findings"] if f["id"] == "CVE-2026-0").get("analysis_state") == "not_affected"
