"""The dashboard digest reads the findings table, not the scan blobs.

It used to load every current run's whole ``result`` for every component in the
workspace, merge and extract in Python, sort the lot, and return three rows: the
work scaled with the workspace while the answer never grew.

Ranking and bounding are SQL now. What stays in Python is the cross-provider
fold, because it is by alias and transitive, and it runs over the ranked
candidates rather than over everything.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache

from sbomify.apps.core.models import Component
from sbomify.apps.core.services.dashboard_page import build_dashboard_context
from sbomify.apps.plugins.models import AssessmentRun
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.vulnerability_scanning.findings import sync_findings
from sbomify.apps.vulnerability_scanning.models import Finding

pytestmark = pytest.mark.django_db


def _scan(sbom: SBOM, findings: list[dict[str, Any]], plugin: str = "osv") -> AssessmentRun:
    """A completed run, projected the way the orchestrator projects one."""
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin,
        category="security",
        status="completed",
        result={"findings": findings, "summary": {"total_findings": len(findings)}},
    )
    sync_findings(run)
    return run


def _finding(advisory: str, severity: str, *, aliases: list[str] | None = None, cvss: float | None = None):
    row: dict[str, Any] = {
        "id": advisory,
        "severity": severity,
        "component": {"name": "openssl", "version": "1.1.1", "ecosystem": "deb"},
    }
    if aliases:
        row["aliases"] = aliases
    if cvss is not None:
        row["cvss_score"] = cvss
    return row


def _component_with(team, findings_by_plugin: dict[str, list[dict[str, Any]]], name: str = "api"):
    component = Component.objects.create(name=name, team=team)
    sbom = SBOM.objects.create(name="s", component=component, version="1.0", format="cyclonedx")
    for plugin, findings in findings_by_plugin.items():
        _scan(sbom, findings, plugin=plugin)
    cache.clear()
    return component


class TestTheSameAdvisoryFromTwoScannersShowsOnce:
    def test_two_scanners_reporting_it_under_different_ids_fold(self, sample_team_with_owner_member) -> None:
        """OSV reports the GHSA carrying the CVE as an alias; Dependency Track
        reports the CVE directly. The two rows share no id, so no DISTINCT folds
        them, which is why the aliases are stored and the fold stays in Python.
        """
        team = sample_team_with_owner_member.team
        _component_with(
            team,
            {
                "osv": [_finding("GHSA-aaaa-bbbb-cccc", "critical", aliases=["CVE-2026-0001"])],
                "dependency-track": [_finding("CVE-2026-0001", "critical")],
            },
        )

        digest = build_dashboard_context(team.id)["needs_attention"]

        assert len(digest) == 1, [row["id"] for row in digest]

    def test_two_genuinely_different_advisories_both_show(self, sample_team_with_owner_member) -> None:
        """The fold must not swallow unrelated findings."""
        team = sample_team_with_owner_member.team
        _component_with(
            team,
            {
                "osv": [_finding("CVE-2026-0001", "critical")],
                "dependency-track": [_finding("CVE-2026-0002", "critical")],
            },
        )

        digest = build_dashboard_context(team.id)["needs_attention"]

        assert {row["id"] for row in digest} == {"CVE-2026-0001", "CVE-2026-0002"}

    def test_a_chain_of_aliases_folds_to_one(self, sample_team_with_owner_member) -> None:
        """The transitive case, which a single claiming pass gets wrong.

        OSV reports GHSA-a aliased to CVE-1; Dependency Track reports CVE-1
        aliased to CVE-2; a third scanner reports CVE-2 alone. All three are one
        vulnerability, and the first and third share no id at all. A pass that
        claims ids as it goes folds the first two and then emits the third
        beside them, because by the time the bridging row arrives the earlier
        ones are already written out.
        """
        team = sample_team_with_owner_member.team
        _component_with(
            team,
            {
                "osv": [_finding("GHSA-a", "critical", aliases=["CVE-1"])],
                "dependency-track": [_finding("CVE-1", "critical", aliases=["CVE-2"])],
                "sbom-verification": [_finding("CVE-2", "critical")],
            },
        )

        digest = build_dashboard_context(team.id)["needs_attention"]

        assert len(digest) == 1, [row["id"] for row in digest]

    def test_a_bridging_row_arriving_last_still_folds(self, sample_team_with_owner_member) -> None:
        """The same chain with the bridge reported by the lowest-ranked scanner,
        so it is the last candidate the database returns."""
        team = sample_team_with_owner_member.team
        _component_with(
            team,
            {
                "osv": [_finding("GHSA-a", "critical")],
                "dependency-track": [_finding("CVE-2", "critical")],
                "sbom-verification": [_finding("CVE-3", "low", aliases=["GHSA-a", "CVE-2"])],
            },
        )

        digest = build_dashboard_context(team.id)["needs_attention"]

        assert len(digest) == 1, [row["id"] for row in digest]

    def test_a_malicious_package_leads(self, sample_team_with_owner_member) -> None:
        """It carries no severity of its own, so ranking on severity alone
        buries it below every real CVE, and it is a remove-now decision."""
        team = sample_team_with_owner_member.team
        nasty = _finding("MAL-2026-0001", "")
        nasty["malicious"] = True
        _component_with(team, {"osv": [_finding("CVE-2026-0001", "critical"), nasty]})

        digest = build_dashboard_context(team.id)["needs_attention"]

        assert digest[0]["id"] == "MAL-2026-0001", [row["id"] for row in digest]

    def test_the_aliases_reach_the_table(self, sample_team_with_owner_member) -> None:
        """Without the column there is nothing to fold on."""
        team = sample_team_with_owner_member.team
        _component_with(team, {"osv": [_finding("GHSA-x", "high", aliases=["CVE-2026-9999"])]})

        stored = Finding.objects.get(advisory_id="GHSA-x")

        assert stored.aliases == ["CVE-2026-9999"]


class TestItNoLongerReadsTheBlobs:
    def test_a_run_whose_result_is_emptied_still_reports_from_the_table(self, sample_team_with_owner_member) -> None:
        """The sharpest available proof that the blob is no longer the source.

        The table is derived and rebuildable, so emptying a stored result is not
        a state to support; it is a way to show which of the two the digest is
        actually reading.
        """
        team = sample_team_with_owner_member.team
        component = _component_with(team, {"osv": [_finding("CVE-2026-0007", "critical")]})
        AssessmentRun.objects.filter(sbom__component_id=component.id).update(result={"findings": []})
        cache.clear()

        digest = build_dashboard_context(team.id)["needs_attention"]

        assert [row["id"] for row in digest] == ["CVE-2026-0007"]

    def test_a_workspace_with_no_findings_is_quiet(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        _component_with(team, {"osv": []})

        assert build_dashboard_context(team.id)["needs_attention"] == []


class TestScopeIsKept:
    def test_a_superseded_sbom_does_not_resurface(self, sample_team_with_owner_member) -> None:
        """``is_current`` is per SBOM, not per component: it means the newest run
        per (sbom, plugin). A component that has uploaded a newer artifact still
        has current rows against the old one, and the dashboard must not show
        vulnerabilities the component has already moved past."""
        team = sample_team_with_owner_member.team
        component = Component.objects.create(name="api", team=team)
        old = SBOM.objects.create(name="s", component=component, version="0.9", format="cyclonedx")
        new = SBOM.objects.create(name="s", component=component, version="1.0", format="cyclonedx")
        _scan(old, [_finding("CVE-OLD", "critical")])
        _scan(new, [_finding("CVE-NEW", "high")])
        cache.clear()

        digest = build_dashboard_context(team.id)["needs_attention"]

        assert [row["id"] for row in digest] == ["CVE-NEW"]

    def test_a_suppressed_finding_is_absent(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        cleared = _finding("CVE-2026-0003", "critical")
        cleared["analysis_state"] = "not_affected"
        _component_with(team, {"osv": [cleared, _finding("CVE-2026-0004", "high")]})

        digest = build_dashboard_context(team.id)["needs_attention"]

        assert [row["id"] for row in digest] == ["CVE-2026-0004"]

    def test_another_workspace_s_findings_stay_out(self, sample_team_with_owner_member) -> None:
        """Not ``sample_team``: that fixture is the same workspace this one owns,
        so a component added to it lands in the digest under test."""
        from sbomify.apps.teams.models import Team

        team = sample_team_with_owner_member.team
        somebody_else = Team.objects.create(name="somebody else")
        _component_with(team, {"osv": [_finding("CVE-MINE", "high")]}, name="mine")
        _component_with(somebody_else, {"osv": [_finding("CVE-THEIRS", "critical")]}, name="theirs")

        digest = build_dashboard_context(team.id)["needs_attention"]

        assert [row["id"] for row in digest] == ["CVE-MINE"]
