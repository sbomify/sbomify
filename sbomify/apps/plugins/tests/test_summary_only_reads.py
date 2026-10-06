"""Readers that show a run's status or counts read the newest runs, and no findings.

A run's ``result`` holds its whole findings list, up to a few MB, and an SBOM
rescanned hourly has hundreds of runs. A badge, a card or a Trust Center row
needs each plugin's newest run, and from it only the summary and metadata.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.tests.shared_fixtures import register_plugin
from sbomify.apps.plugins.apis import get_sbom_assessment_badge, get_sbom_assessments
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.public_assessment_utils import (
    get_components_latest_sbom_assessments_batch,
    get_products_latest_sbom_assessments_batch,
)
from sbomify.apps.sboms.models import SBOM, ProductComponent

pytestmark = pytest.mark.django_db

# The whole column, as opposed to a ``result -> 'summary'`` slice of it.
WHOLE_RESULT = re.compile(r'"plugins_assessment_runs"\."result"(?!\s*->)')

VULNERABLE = {
    "summary": {"total_findings": 1, "by_severity": {"high": 1}},
    "findings": [{"id": "CVE-2026-0001", "severity": "high"}],
}
PASSING = {
    "summary": {"total_findings": 3, "pass_count": 3, "fail_count": 0, "error_count": 0, "warning_count": 0},
    "metadata": {"standard_name": "NTIA Minimum Elements", "standard_version": "2021"},
    "findings": [{"id": f"check-{i}", "status": "pass"} for i in range(3)],
}


def _run(sbom: SBOM, plugin: str, category: str, result: dict[str, Any]) -> None:
    register_plugin(plugin, category)
    AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin,
        plugin_version="1.0.0",
        plugin_config_hash="",
        category=category,
        run_reason="on_upload",
        status="completed",
        result=result,
    )


@pytest.fixture
def scanned(sample_team_with_owner_member) -> SBOM:
    """A public SBOM rescanned five times, plus one passing compliance check."""
    component = Component.objects.create(
        name="scanned", team=sample_team_with_owner_member.team, visibility=Component.Visibility.PUBLIC
    )
    sbom = SBOM.objects.create(
        name="app",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="a.json",
        component=component,
    )
    for _ in range(5):
        _run(sbom, "osv", "security", VULNERABLE)
    _run(sbom, "ntia-minimum-elements-2021", "compliance", PASSING)
    return sbom


def _whole_result_reads(queries: CaptureQueriesContext) -> list[str]:
    return [query["sql"] for query in queries if WHOLE_RESULT.search(query["sql"])]


def test_without_history_only_the_newest_runs_are_read_whole(scanned, sample_team_with_owner_member):
    request = RequestFactory().get(f"/api/v1/plugins/assessments/{scanned.id}")
    request.user = sample_team_with_owner_member.user

    with CaptureQueriesContext(connection) as queries:
        response = get_sbom_assessments(request, str(scanned.id), findings_limit=1, include_history=False)

    assert {run.plugin_name for run in response.latest_runs} == {"osv", "ntia-minimum-elements-2021"}
    reads = _whole_result_reads(queries)
    assert reads
    assert all('"plugins_assessment_runs"."id" IN' in sql for sql in reads)


def test_the_badge_reads_no_findings(scanned, sample_team_with_owner_member):
    request = RequestFactory().get(f"/api/v1/plugins/assessments/{scanned.id}/badge")
    request.user = sample_team_with_owner_member.user

    with CaptureQueriesContext(connection) as queries:
        badge = get_sbom_assessment_badge(request, str(scanned.id))

    assert (badge.failing_count, badge.passing_count) == (1, 1)
    assert not _whole_result_reads(queries)


def test_the_badge_counts_runs_saved_before_the_summary_columns(scanned, sample_team_with_owner_member):
    """Runs saved before migration 0015 hold their summary only inside
    ``result`` until ``backfill_result_summaries`` runs, so the badge reads the
    slice of ``result`` and not the stored column."""
    AssessmentRun.objects.filter(sbom=scanned).update(result_summary=None, result_skipped=None)
    request = RequestFactory().get(f"/api/v1/plugins/assessments/{scanned.id}/badge")
    request.user = sample_team_with_owner_member.user

    badge = get_sbom_assessment_badge(request, str(scanned.id))

    assert (badge.failing_count, badge.passing_count) == (1, 1)


def test_trust_center_batches_read_no_findings(scanned):
    component = scanned.component
    product = Product.objects.create(name="p", team=component.team, is_public=True)
    ProductComponent.objects.create(product=product, component=component)

    with CaptureQueriesContext(connection) as queries:
        by_product = get_products_latest_sbom_assessments_batch([product])
        by_component = get_components_latest_sbom_assessments_batch([component])

    assert [a.plugin_name for a in by_product[str(product.id)]] == ["ntia-minimum-elements-2021"]
    [passing] = by_component[str(component.id)]
    assert (passing.standard_name, passing.pass_count) == ("NTIA Minimum Elements", 3)
    assert not _whole_result_reads(queries)
