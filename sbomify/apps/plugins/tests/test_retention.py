"""Assessment-run retention.

The table is append-only and had no policy at all: ~10,300 rows growing ~170/day
when #1120 was filed. The two rules have to compose, so most of these cover the
interaction rather than either rule alone.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.retention import prunable_run_ids, prune_assessment_runs
from sbomify.apps.plugins.sdk.enums import RunReason, RunStatus

pytestmark = pytest.mark.django_db


def _run(sbom, plugin: str, *, days_ago: int) -> AssessmentRun:
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin,
        plugin_version="1.0.0",
        plugin_config_hash="0" * 64,
        category="security",
        run_reason=RunReason.MANUAL.value,
        status=RunStatus.COMPLETED.value,
    )
    AssessmentRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
    return run


class TestKeepRule:
    def test_a_pair_under_quota_keeps_everything_however_old(self, sample_sbom):
        for age in (400, 500, 600):
            _run(sample_sbom, "osv", days_ago=age)

        assert prunable_run_ids(keep_per_plugin=10, min_age_days=30) == []

    def test_beyond_the_quota_the_oldest_go(self, sample_sbom):
        for age in range(100, 106):
            _run(sample_sbom, "osv", days_ago=age)

        doomed = prunable_run_ids(keep_per_plugin=3, min_age_days=30)

        assert len(doomed) == 3

    def test_the_quota_is_per_plugin_not_per_sbom(self, sample_sbom):
        """Otherwise a chatty scanner evicts a quiet one's only run."""
        for age in range(100, 110):
            _run(sample_sbom, "osv", days_ago=age)
        quiet = _run(sample_sbom, "dependency-track", days_ago=400)

        doomed = prunable_run_ids(keep_per_plugin=3, min_age_days=30)

        assert quiet.id not in doomed

    def test_the_newest_run_is_never_prunable(self, sample_sbom):
        """Deleting it would empty a card with no newer result to replace it."""
        newest = _run(sample_sbom, "osv", days_ago=100)
        for age in range(101, 120):
            _run(sample_sbom, "osv", days_ago=age)

        assert newest.id not in prunable_run_ids(keep_per_plugin=1, min_age_days=30)


class TestTtlFloor:
    def test_nothing_recent_is_touched_however_many_there_are(self, sample_sbom):
        """A retry storm this afternoon must not erase this morning's run."""
        for _ in range(50):
            _run(sample_sbom, "osv", days_ago=1)

        assert prunable_run_ids(keep_per_plugin=3, min_age_days=30) == []

    def test_the_two_rules_compose(self, sample_sbom):
        """Recent runs fill the quota, so the old ones become prunable even
        though the recent ones stay."""
        recent = [_run(sample_sbom, "osv", days_ago=1) for _ in range(3)]
        old = [_run(sample_sbom, "osv", days_ago=200) for _ in range(2)]

        doomed = set(prunable_run_ids(keep_per_plugin=3, min_age_days=30))

        assert doomed == {run.id for run in old}
        assert not doomed & {run.id for run in recent}


class TestPruning:
    def test_it_deletes_and_reports_the_count(self, sample_sbom):
        for age in range(100, 106):
            _run(sample_sbom, "osv", days_ago=age)

        removed = prune_assessment_runs(keep_per_plugin=3, min_age_days=30)

        assert removed == 3
        assert AssessmentRun.objects.count() == 3

    def test_a_dry_run_deletes_nothing(self, sample_sbom):
        for age in range(100, 106):
            _run(sample_sbom, "osv", days_ago=age)

        counted = prune_assessment_runs(keep_per_plugin=3, min_age_days=30, dry_run=True)

        assert counted == 3
        assert AssessmentRun.objects.count() == 6

    def test_batching_deletes_everything_it_selected(self, sample_sbom):
        """Batched so a first run against a large table holds short locks; the
        batch size must not change the outcome."""
        for age in range(100, 112):
            _run(sample_sbom, "osv", days_ago=age)

        removed = prune_assessment_runs(keep_per_plugin=2, min_age_days=30, batch_size=3)

        assert removed == 10
        assert AssessmentRun.objects.count() == 2

    def test_an_empty_table_is_a_no_op(self):
        assert prune_assessment_runs() == 0
