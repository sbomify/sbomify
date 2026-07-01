"""Plugins security: fail-closed on scanner error, and access control on assessment reads."""

import pytest
from django.test import Client

from sbomify.apps.core.models import Component
from sbomify.apps.plugins.apis import _is_run_failing
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM


def _run(sbom, summary):
    full_summary = {"total_findings": 0, "pass_count": 0, "fail_count": 0, "warning_count": 0, "error_count": 0}
    full_summary.update(summary)
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        plugin_version="1.0.0",
        plugin_config_hash="h",
        category="security",
        run_reason="on_upload",
        status="completed",
        result={
            "plugin_name": "osv",
            "plugin_version": "1.0.0",
            "category": "security",
            "assessed_at": "2026-07-01T00:00:00Z",
            "summary": full_summary,
            "findings": [],
        },
    )


def _sbom(team, visibility):
    component = Component.objects.create(
        name=f"comp-{visibility}", team=team, visibility=visibility, component_type="bom"
    )
    return SBOM.objects.create(name="s", component=component, format="cyclonedx", format_version="1.6")


@pytest.mark.django_db
def test_errored_security_run_is_failing(sample_team_with_owner_member):
    """An errored security scan (error_count>0, no by_severity) must read as failing, not clean."""
    sbom = _sbom(sample_team_with_owner_member.team, Component.Visibility.PUBLIC)
    errored = _run(sbom, {"total_findings": 1, "error_count": 1})  # no by_severity
    clean = _run(sbom, {"total_findings": 0, "error_count": 0, "by_severity": {}})

    assert _is_run_failing(errored) is True
    assert _is_run_failing(clean) is False


@pytest.mark.django_db
def test_assessments_not_leaked_for_private_sbom(sample_team_with_owner_member):
    """An anonymous caller must not read a private SBOM's assessment findings."""
    sbom = _sbom(sample_team_with_owner_member.team, Component.Visibility.PRIVATE)
    _run(sbom, {"total_findings": 3, "by_severity": {"high": 3}})

    resp = Client().get(f"/api/v1/plugins/assessments/{sbom.id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["all_runs"] == []
    assert data["status_summary"]["overall_status"] == "no_assessments"


@pytest.mark.django_db
def test_assessments_visible_for_public_sbom(sample_team_with_owner_member):
    """A public SBOM's assessments remain readable anonymously (badges/public pages)."""
    sbom = _sbom(sample_team_with_owner_member.team, Component.Visibility.PUBLIC)
    _run(sbom, {"total_findings": 3, "by_severity": {"high": 3}})

    resp = Client().get(f"/api/v1/plugins/assessments/{sbom.id}")

    assert resp.status_code == 200
    assert len(resp.json()["all_runs"]) == 1


@pytest.mark.django_db
def test_badge_not_leaked_for_private_sbom(sample_team_with_owner_member):
    """The badge endpoint is gated the same way as the assessments endpoint."""
    sbom = _sbom(sample_team_with_owner_member.team, Component.Visibility.PRIVATE)
    _run(sbom, {"total_findings": 3, "by_severity": {"high": 3}})

    resp = Client().get(f"/api/v1/plugins/assessments/{sbom.id}/badge")

    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_status"] == "no_assessments"
    assert data["plugins"] == []
