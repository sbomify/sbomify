"""The risk tools' numbers must match what the dashboards report.

These pin the three ways the module could quietly diverge from the UI: a
pending or failed rescan shadowing the last completed result, VEX dispositions
uploaded after a scan being ignored, and severity buckets an agent can read in
the summary but not reach through the list filter.
"""

from __future__ import annotations

import pytest

from sbomify.apps.core.models import Component
from sbomify.apps.mcp.tools import risk
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM

CRITICAL_FINDING = {
    "findings": [
        {
            "id": "CVE-2025-11111",
            "severity": "critical",
            "cvss_score": 9.8,
            "component": {"name": "libexample", "version": "1.0.0", "purl": "pkg:pypi/libexample@1.0.0"},
        }
    ]
}


def _sbom(team, name: str = "risk-sbom") -> SBOM:
    component = Component.objects.create(name=f"{name}-component", team=team)
    return SBOM.objects.create(
        name=name,
        version="1.0.0",
        format="cyclonedx",
        format_version="1.6",
        sbom_filename=f"{name}.json",
        component=component,
    )


def _run(sbom: SBOM, *, status: str = "completed", result: dict | None = CRITICAL_FINDING) -> AssessmentRun:
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name="osv",
        plugin_version="1.0.0",
        plugin_config_hash="",
        category="security",
        run_reason="on_upload",
        status=status,
        result=result if status == "completed" else None,
    )


@pytest.mark.django_db
def test_pending_rescan_does_not_shadow_the_last_completed_result(mcp_owner):
    """A queued or failed rescan must not make an SBOM read as scanned-and-clean.

    The dashboards only consider completed runs; a pending row has no result,
    so letting it win the newest-per-provider pick would report zero findings
    (and the SBOM as scanned) while the UI still shows the last real counts.
    """
    _, bound, _ = mcp_owner
    sbom = _sbom(bound)
    _run(sbom, status="completed")
    _run(sbom, status="pending")

    rows, scanned = risk._rows_for(risk._security_runs(bound))

    assert scanned == {sbom.id}
    assert risk._counts(rows)["critical"] == 1

    _run(sbom, status="failed")
    rows, _ = risk._rows_for(risk._security_runs(bound))
    assert risk._counts(rows)["critical"] == 1


@pytest.mark.django_db
def test_vex_uploaded_after_the_scan_suppresses_the_finding(mcp_owner, monkeypatch):
    """A finding the customer dispositioned via VEX must not be reported live.

    The dashboards resolve VEX statements at read time, so a VEX uploaded
    after the scan already suppresses there; the agent has to agree.
    """
    from sbomify.apps.vulnerability_scanning import vex

    _, bound, _ = mcp_owner
    sbom = _sbom(bound)
    _run(sbom, status="completed")

    monkeypatch.setattr(
        vex,
        "load_vex_suppressions",
        lambda component_id, cache=None: [
            # The shape derive_vex_suppressions produces: ids normalised to
            # lowercase, packages as a set, product_scoped statements matching
            # on id alone.
            {
                "ids": {"cve-2025-11111"},
                "state": "not_affected",
                "justification": "code_not_reachable",
                "source": "vex-import",
                "product_scoped": True,
                "packages": set(),
            }
        ],
    )

    rows, _ = risk._rows_for(risk._security_runs(bound))

    assert len(rows) == 1
    assert rows[0]["vex_suppressed"] is True
    assert risk._counts(rows)["total"] == 0


@pytest.mark.django_db
def test_every_summary_bucket_is_reachable_through_the_list_filter(mcp_owner):
    """The name a count appears under is the name the list filter accepts."""
    _, bound, _ = mcp_owner
    sbom = _sbom(bound)
    _run(
        sbom,
        status="completed",
        result={
            "findings": [
                {"id": "CVE-2025-1", "severity": "info", "component": {"name": "a"}},
                {"id": "CVE-2025-2", "severity": "moderate", "component": {"name": "b"}},
            ]
        },
    )

    rows, _ = risk._rows_for(risk._security_runs(bound))
    counts = risk._counts(rows)

    assert counts["info"] == 1
    assert counts["unknown"] == 1
    for row in rows:
        assert risk._severity_bucket(row) in risk.SEVERITIES


def test_severities_mirror_the_shared_rank():
    """SEVERITIES is hand-written to keep imports lazy; hold it to the source."""
    from sbomify.apps.vulnerability_scanning.utils import SEVERITY_RANK

    assert risk.SEVERITIES == (*SEVERITY_RANK, "unknown")


@pytest.mark.django_db
def test_only_the_latest_sbom_per_component_counts(mcp_owner):
    """Historical SBOM versions must not stack their findings.

    The dashboards count only the newest bom_type=sbom per component; a
    component uploading an SBOM per build would otherwise report the same
    CVE once per upload, and the tool docstring promises dashboard parity.
    """
    from datetime import timedelta

    from django.utils import timezone

    _, bound, _ = mcp_owner
    component = Component.objects.create(name="versioned-component", team=bound)

    def _versioned(version: str) -> SBOM:
        return SBOM.objects.create(
            name="versioned",
            version=version,
            format="cyclonedx",
            format_version="1.6",
            sbom_filename=f"versioned-{version}.json",
            component=component,
        )

    old = _versioned("1.0.0")
    new = _versioned("2.0.0")
    SBOM.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=1))

    _run(
        old,
        status="completed",
        result={
            "findings": [{"id": "CVE-2024-0001", "severity": "high", "component": {"name": "oldlib", "version": "1"}}]
        },
    )
    _run(new, status="completed")

    rows, scanned = risk._rows_for(risk._security_runs(bound))
    counts = risk._counts(rows)

    assert scanned == {new.id}
    assert counts["critical"] == 1
    assert counts["high"] == 0
    assert counts["total"] == 1
