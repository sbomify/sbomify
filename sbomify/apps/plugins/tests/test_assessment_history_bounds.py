"""The assessments endpoint must not return a response that grows with the SBOM's age.

``get_sbom_assessments`` returned every run an SBOM had ever had, each with its
own findings array, from an endpoint declared ``auth=None`` and reachable for any
public component. A scheduled scanner writes a run per SBOM per cycle, so the
response size was a function of how long the artifact had existed: at an hourly
cadence, 24 more runs a day, forever. The docstring already recorded where that
ends — a 31 MB body and a 504 at the gateway.

Two properties are pinned here. The response is bounded by the request, and the
latest run per plugin is still found when it falls outside the history window —
deriving "latest" from the truncated history would silently drop a plugin whose
last run is older than the newest ``history_limit`` runs, which is exactly the
shape of a quiet compliance plugin next to a noisy hourly scanner.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from sbomify.apps.core.models import Component
from sbomify.apps.plugins.apis import DEFAULT_HISTORY_LIMIT, get_sbom_assessments
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.plugins.sdk.enums import AssessmentCategory, RunReason, RunStatus
from sbomify.apps.sboms.models import SBOM


def _result(finding_id: str) -> dict[str, Any]:
    return {
        "plugin_name": "osv",
        "plugin_version": "1.0.0",
        "category": "security",
        "assessed_at": timezone.now().isoformat(),
        "summary": {"total_findings": 1, "by_severity": {"high": 1}},
        "findings": [{"id": finding_id, "severity": "high", "component": {"name": "foo", "version": "1"}}],
    }


def _run(sbom: SBOM, plugin: str, *, minutes_ago: int, finding_id: str = "CVE-2026-1") -> AssessmentRun:
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin,
        plugin_version="1.0.0",
        plugin_config_hash="0" * 64,
        category=AssessmentCategory.SECURITY.value,
        run_reason=RunReason.SCHEDULED_REFRESH.value,
        status=RunStatus.COMPLETED.value,
        result=_result(finding_id),
    )
    # created_at is auto_now_add, so the age has to be written back.
    AssessmentRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(minutes=minutes_ago))
    return run


@pytest.fixture
def scanned_sbom(sample_team_with_owner_member):
    component = Component.objects.create(name="c", team=sample_team_with_owner_member.team)
    return SBOM.objects.create(
        name="app",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="a.json",
        component=component,
    )


def _call(rf, sbom_id: str, **kwargs: Any):
    """Invoke the endpoint function directly, as the component page does."""
    request = rf.get("/")
    request.user = None  # anonymous: the public read path this endpoint serves
    return get_sbom_assessments(request, sbom_id, **kwargs)


@pytest.mark.django_db
class TestTheHistoryIsBounded:
    def test_a_long_history_is_truncated_to_the_limit(self, scanned_sbom, rf, monkeypatch):
        monkeypatch.setattr("sbomify.apps.plugins.apis._readable_sbom", lambda request, sbom_id: scanned_sbom)
        for minute in range(1, 31):
            _run(scanned_sbom, "osv", minutes_ago=minute)

        response = _call(rf, scanned_sbom.id, history_limit=10)

        assert len(response.all_runs) == 10
        # …and the caller can tell it was truncated rather than guessing.
        assert response.all_runs_total == 30

    def test_the_truncation_keeps_the_newest_runs(self, scanned_sbom, rf, monkeypatch):
        monkeypatch.setattr("sbomify.apps.plugins.apis._readable_sbom", lambda request, sbom_id: scanned_sbom)
        newest = _run(scanned_sbom, "osv", minutes_ago=1)
        for minute in range(2, 12):
            _run(scanned_sbom, "osv", minutes_ago=minute)

        response = _call(rf, scanned_sbom.id, history_limit=3)

        assert response.all_runs[0].id == str(newest.id)

    def test_an_untruncated_history_reports_its_real_size(self, scanned_sbom, rf, monkeypatch):
        """``all_runs_total`` must equal len(all_runs) when nothing was dropped,
        or a caller cannot use it to detect truncation."""
        monkeypatch.setattr("sbomify.apps.plugins.apis._readable_sbom", lambda request, sbom_id: scanned_sbom)
        for minute in range(1, 4):
            _run(scanned_sbom, "osv", minutes_ago=minute)

        response = _call(rf, scanned_sbom.id)

        assert response.all_runs_total == 3 == len(response.all_runs)

    def test_the_default_limit_applies_when_the_caller_says_nothing(self, scanned_sbom, rf, monkeypatch):
        """The whole point: an unauthenticated caller passing no parameters must
        not be able to ask for an unbounded response."""
        monkeypatch.setattr("sbomify.apps.plugins.apis._readable_sbom", lambda request, sbom_id: scanned_sbom)
        for minute in range(1, DEFAULT_HISTORY_LIMIT + 6):
            _run(scanned_sbom, "osv", minutes_ago=minute)

        response = _call(rf, scanned_sbom.id)

        assert len(response.all_runs) == DEFAULT_HISTORY_LIMIT
        assert response.all_runs_total == DEFAULT_HISTORY_LIMIT + 5

    def test_include_history_false_still_drops_it_entirely(self, scanned_sbom, rf, monkeypatch):
        monkeypatch.setattr("sbomify.apps.plugins.apis._readable_sbom", lambda request, sbom_id: scanned_sbom)
        for minute in range(1, 6):
            _run(scanned_sbom, "osv", minutes_ago=minute)

        response = _call(rf, scanned_sbom.id, include_history=False)

        assert response.all_runs == []
        # The count is still honest about what exists.
        assert response.all_runs_total == 5


@pytest.mark.django_db
class TestLatestPerPluginSurvivesTruncation:
    def test_a_quiet_plugin_outside_the_window_is_still_the_latest(self, scanned_sbom, rf, monkeypatch):
        """The regression this endpoint's shape invites: a compliance plugin that
        ran once a week ago, beside a scanner running hourly. Derive "latest"
        from the truncated history and the compliance card disappears."""
        monkeypatch.setattr("sbomify.apps.plugins.apis._readable_sbom", lambda request, sbom_id: scanned_sbom)
        quiet = _run(scanned_sbom, "ntia-minimum-elements-2021", minutes_ago=10_000)
        for minute in range(1, 21):
            _run(scanned_sbom, "osv", minutes_ago=minute)

        response = _call(rf, scanned_sbom.id, history_limit=5)

        plugins = {run.plugin_name for run in response.latest_runs}
        assert plugins == {"osv", "ntia-minimum-elements-2021"}
        assert str(quiet.id) in {run.id for run in response.latest_runs}
        # It is outside the history window, which is the point of the test.
        assert str(quiet.id) not in {run.id for run in response.all_runs}

    def test_the_status_summary_reads_the_latest_runs_not_the_window(self, scanned_sbom, rf, monkeypatch):
        """The summary counts one assessment per plugin. Computing it from a
        truncated window would have reported only the noisy plugin."""
        monkeypatch.setattr("sbomify.apps.plugins.apis._readable_sbom", lambda request, sbom_id: scanned_sbom)
        _run(scanned_sbom, "ntia-minimum-elements-2021", minutes_ago=10_000)
        for minute in range(1, 21):
            _run(scanned_sbom, "osv", minutes_ago=minute)

        response = _call(rf, scanned_sbom.id, history_limit=2)

        assert response.status_summary.total_assessments == 2


@pytest.mark.django_db
class TestOnlySerialisedRunsAreFetched:
    """The response carries the blob for the runs it serialises and no others.
    That is what makes the cost proportional to the request: the identity pass
    selects over two small columns, so a thousand-run history is a thousand rows
    of (id, plugin_name) rather than a thousand de-TOASTed findings arrays."""

    def test_no_query_projects_more_blobs_than_the_response_serialises(self, scanned_sbom, rf, monkeypatch):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        monkeypatch.setattr("sbomify.apps.plugins.apis._readable_sbom", lambda request, sbom_id: scanned_sbom)
        for minute in range(1, 41):
            _run(scanned_sbom, "osv", minutes_ago=minute)

        with CaptureQueriesContext(connection) as captured:
            response = _call(rf, scanned_sbom.id, history_limit=5)

        blob_queries = [query["sql"] for query in captured.captured_queries if '."result"' in query["sql"]]
        # One query, for the union of latest-per-plugin and the history window,
        # which here is the same 5 runs the response returns.
        assert len(blob_queries) == 1
        assert len(response.all_runs) == 5

    def test_the_identity_pass_does_not_read_the_blob(self, scanned_sbom, rf, monkeypatch):
        """A history far larger than the window must not be de-TOASTed to be counted."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        monkeypatch.setattr("sbomify.apps.plugins.apis._readable_sbom", lambda request, sbom_id: scanned_sbom)
        for minute in range(1, 41):
            _run(scanned_sbom, "osv", minutes_ago=minute)

        with CaptureQueriesContext(connection) as captured:
            response = _call(rf, scanned_sbom.id, include_history=False)

        assert response.all_runs_total == 40
        blob_queries = [query["sql"] for query in captured.captured_queries if '."result"' in query["sql"]]
        # Only the latest run per plugin: one plugin here, so one blob.
        assert len(blob_queries) == 1
        assert len(response.latest_runs) == 1
