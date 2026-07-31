"""Tests for the application-maintained result_summary/result_skipped columns."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.models import Component
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.teams.models import Team


@pytest.mark.django_db
class TestResultColumns:
    """save() keeps result_summary/result_skipped in lockstep with result."""

    @pytest.fixture
    def sbom(self) -> SBOM:
        BillingPlan.objects.get_or_create(key="business", defaults={"name": "Business Plan"})
        team = Team.objects.create(name="Result Columns Team", key="result-columns-team", billing_plan="business")
        component = Component.objects.create(name="result-columns-component", team=team, component_type="bom")
        return SBOM.objects.create(
            name="result-columns-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="test.cdx.json",
            source="test",
        )

    def _make_run(self, sbom: SBOM, result: dict | None) -> AssessmentRun:
        return AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="osv",
            plugin_version="1.0.0",
            category="security",
            run_reason="on_upload",
            status="completed",
            result=result,
        )

    def test_create_populates_columns(self, sbom: SBOM) -> None:
        run = self._make_run(
            sbom,
            {"summary": {"total_findings": 3}, "metadata": {"skipped": True}, "findings": []},
        )
        run.refresh_from_db()
        assert run.result_summary == {"total_findings": 3}
        assert run.result_skipped is True

    def test_create_without_result_leaves_columns_null(self, sbom: SBOM) -> None:
        run = self._make_run(sbom, None)
        run.refresh_from_db()
        assert run.result_summary is None
        assert run.result_skipped is None

    def test_non_dict_summary_and_junk_skipped_yield_null(self, sbom: SBOM) -> None:
        run = self._make_run(sbom, {"summary": "n/a", "metadata": {"skipped": "n/a"}})
        run.refresh_from_db()
        assert run.result_summary is None
        assert run.result_skipped is None

    def test_skipped_false_is_preserved(self, sbom: SBOM) -> None:
        run = self._make_run(sbom, {"summary": {"total_findings": 0}, "metadata": {"skipped": False}})
        run.refresh_from_db()
        assert run.result_skipped is False

    def test_update_fields_with_result_syncs_columns(self, sbom: SBOM) -> None:
        """The reannotation path: save(update_fields=["result"]) must not leave the columns stale."""
        run = self._make_run(sbom, {"summary": {"total_findings": 5}, "findings": []})
        run.result = {"summary": {"total_findings": 1}, "metadata": {"skipped": False}, "findings": []}
        run.save(update_fields=["result"])
        run.refresh_from_db()
        assert run.result_summary == {"total_findings": 1}
        assert run.result_skipped is False

    def test_update_fields_without_result_does_not_write_columns(self, sbom: SBOM) -> None:
        run = self._make_run(sbom, {"summary": {"total_findings": 5}})
        AssessmentRun.objects.filter(id=run.id).update(result_summary=None, result_skipped=None)
        run.result_summary = None
        run.status = "failed"
        run.save(update_fields=["status"])
        # not recomputed in memory either — a status-only save must not touch result
        assert run.result_summary is None
        run.refresh_from_db()
        assert run.result_summary is None

    def test_save_on_deferred_instance_does_not_refetch_result(self, sbom: SBOM) -> None:
        run = self._make_run(sbom, {"summary": {"total_findings": 5}})
        deferred = AssessmentRun.objects.only("id", "status").get(id=run.id)
        deferred.status = "failed"
        deferred.save()
        assert "result" in deferred.get_deferred_fields()
        run.refresh_from_db()
        assert run.result_summary == {"total_findings": 5}


@pytest.mark.django_db
class TestBackfillResultSummaries:
    """The backfill command fills legacy NULL columns and terminates."""

    @pytest.fixture
    def sbom(self) -> SBOM:
        BillingPlan.objects.get_or_create(key="business", defaults={"name": "Business Plan"})
        team = Team.objects.create(name="Backfill Team", key="backfill-team", billing_plan="business")
        component = Component.objects.create(name="backfill-component", team=team, component_type="bom")
        return SBOM.objects.create(
            name="backfill-sbom",
            component=component,
            format="cyclonedx",
            format_version="1.5",
            sbom_filename="test.cdx.json",
            source="test",
        )

    def _make_legacy_run(self, sbom: SBOM, result: dict | None) -> AssessmentRun:
        """Create a run, then null the columns queryset-side to simulate a pre-column row."""
        run = AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="osv",
            plugin_version="1.0.0",
            category="security",
            run_reason="on_upload",
            status="completed",
            result=result,
        )
        AssessmentRun.objects.filter(id=run.id).update(result_summary=None, result_skipped=None)
        return run

    def test_backfills_legacy_rows_and_terminates(self, sbom: SBOM) -> None:
        filled = self._make_legacy_run(
            sbom, {"summary": {"total_findings": 7}, "metadata": {"skipped": True}, "findings": []}
        )
        # summary computes to NULL forever — must not loop the command
        scalar = self._make_legacy_run(sbom, {"summary": "n/a", "metadata": {"skipped": False}})
        no_result = self._make_legacy_run(sbom, None)

        out = StringIO()
        call_command("backfill_result_summaries", "--batch-size", "1", stdout=out)

        filled.refresh_from_db()
        assert filled.result_summary == {"total_findings": 7}
        assert filled.result_skipped is True

        scalar.refresh_from_db()
        assert scalar.result_summary is None
        assert scalar.result_skipped is False

        no_result.refresh_from_db()
        assert no_result.result_summary is None
        assert "done:" in out.getvalue()

    @pytest.mark.parametrize("bad_size", ["0", "-5"])
    def test_rejects_non_positive_batch_size(self, bad_size: str) -> None:
        with pytest.raises(CommandError, match="batch-size"):
            call_command("backfill_result_summaries", "--batch-size", bad_size)

    def test_leaves_already_populated_rows_untouched(self, sbom: SBOM) -> None:
        run = AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name="osv",
            plugin_version="1.0.0",
            category="security",
            run_reason="on_upload",
            status="completed",
            result={"summary": {"total_findings": 2}, "findings": []},
        )
        out = StringIO()
        call_command("backfill_result_summaries", stdout=out)
        run.refresh_from_db()
        assert run.result_summary == {"total_findings": 2}
