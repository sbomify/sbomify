"""One malformed AssessmentRun.result must not blank the whole assessments response.

A legacy or hand-written result blob that predates the current schema (or drifts
from it) used to raise a ValidationError inside serialization, failing the
entire endpoint — and the component-item view swallowed that exception, so the
Assessment Results section silently disappeared for every run of the SBOM.
"""

from __future__ import annotations

import pytest
from django.test import RequestFactory

from sbomify.apps.core.models import Component
from sbomify.apps.plugins.apis import get_sbom_assessments
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM

VALID_RESULT = {
    "plugin_name": "osv",
    "plugin_version": "1.0.0",
    "category": "security",
    "assessed_at": "2026-07-14T00:00:00Z",
    "schema_version": "1.0",
    "summary": {"total_findings": 1, "by_severity": {"critical": 1}},
    "findings": [
        {
            "id": "CVE-2026-0001",
            "title": "example",
            "description": "example finding",
            "severity": "critical",
        }
    ],
}

# Missing the required envelope (plugin_name/category/assessed_at, ...) — the
# shape a legacy plugin version or external writer can leave behind.
MALFORMED_RESULT = {
    "summary": {"total_findings": 2},
    "findings": [{"id": "chk-1", "title": "no description key"}],
}


def _make_run(sbom: SBOM, plugin: str, result: dict) -> AssessmentRun:
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin,
        plugin_version="1.0.0",
        plugin_config_hash="",
        category="security",
        run_reason="on_upload",
        status="completed",
        result=result,
    )


@pytest.mark.django_db
def test_malformed_result_degrades_that_run_only(sample_team_with_owner_member):
    component = Component.objects.create(name="malformed-result-c", team=sample_team_with_owner_member.team)
    sbom = SBOM.objects.create(
        name="app",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="a.json",
        component=component,
    )
    _make_run(sbom, "osv", VALID_RESULT)
    _make_run(sbom, "legacy-plugin", MALFORMED_RESULT)

    request = RequestFactory().get(f"/api/v1/plugins/assessments/{sbom.id}")
    request.user = sample_team_with_owner_member.user

    response = get_sbom_assessments(request, str(sbom.id))
    data = response.model_dump(mode="json")

    by_plugin = {run["plugin_name"]: run for run in data["latest_runs"]}
    assert set(by_plugin) == {"osv", "legacy-plugin"}
    # The valid run keeps its result; the malformed one degrades to result=None
    # instead of failing the whole response.
    assert by_plugin["osv"]["result"]["summary"]["total_findings"] == 1
    assert by_plugin["legacy-plugin"]["result"] is None
    assert by_plugin["legacy-plugin"]["status"] == "completed"
    assert data["status_summary"]["total_assessments"] == 2


@pytest.mark.django_db
def test_non_result_validation_error_still_raises(sample_team_with_owner_member):
    """Only the result payload may degrade; a validation failure on any other
    field is a real bug and must surface instead of being blamed on the blob."""
    from pydantic import ValidationError

    from sbomify.apps.plugins.apis import _run_to_schema

    component = Component.objects.create(name="raise-c", team=sample_team_with_owner_member.team)
    sbom = SBOM.objects.create(
        name="app",
        version="1.0.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename="a.json",
        component=component,
    )
    run = _make_run(sbom, "osv", VALID_RESULT)
    # An unsaved-style hole outside `result`: created_at is required by the schema.
    run.created_at = None

    with pytest.raises(ValidationError):
        _run_to_schema(run, {})
