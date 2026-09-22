"""Nothing scanned is not nothing found.

A skipped run stores zero findings exactly as a clean scan does, so the two were
indistinguishable downstream and an artifact no scanner could read rendered as
**Clean**. #1371 and #1372 stopped those runs claiming a public pass; they did
not reach the internal tables, which is where an operator decides what to do.

Three states now, from one predicate:

    Clean            scanned, nothing found
    Nothing scanned  a scan ran and matched no packages
    Not scanned      no run at all
"""

from __future__ import annotations

from typing import Any

import pytest

from sbomify.apps.vulnerability_scanning.utils import result_scanned_nothing

SKIPPED = {"summary": {"total_findings": 1, "warning_count": 1}, "metadata": {"skipped": True}}
CLEAN = {
    "summary": {"total_findings": 0, "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0}},
    "findings": [],
    "metadata": {"scanner": "osv-scanner"},
}


class TestThePredicate:
    def test_a_skipped_run_scanned_nothing(self) -> None:
        assert result_scanned_nothing(SKIPPED) is True

    def test_a_clean_run_did_not(self) -> None:
        assert result_scanned_nothing(CLEAN) is False

    @pytest.mark.parametrize("value", [None, {}, {"metadata": None}, {"metadata": {}}, "not a dict", []])
    def test_anything_unexpected_is_not_a_skip(self, value: Any) -> None:
        """False is the safe default here: mistaking a real scan for a skip
        withholds a badge that was earned, which is its own defect."""
        assert result_scanned_nothing(value) is False


@pytest.mark.django_db
class TestTheRowStatus:
    """Product and workspace tables share the same assessment state."""

    def _row(self, workspace: Any, results: list[dict[str, Any]]) -> dict[str, Any]:
        from sbomify.apps.core.models import Component
        from sbomify.apps.core.services.inventory_page import build_inventory_snapshot
        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.sboms.models import SBOM
        from sbomify.apps.vulnerability_scanning.findings import sync_findings

        component = Component.objects.create(name="Library", team=workspace)
        sbom = SBOM.objects.create(name="bom", component=component, format="cyclonedx")
        for index, result in enumerate(results):
            run = AssessmentRun.objects.create(
                sbom=sbom, plugin_name=f"scanner-{index}", category="security", status="completed", result=result
            )
            sync_findings(run)
        return build_inventory_snapshot(workspace, "components")["rows"][0]

    def test_no_run_is_not_scanned(self, sample_team_with_owner_member) -> None:
        row = self._row(sample_team_with_owner_member.team, [])

        assert row["scan_label"] == "Not assessed"
        assert row["assessed"] is False

    def test_a_skipped_run_is_its_own_state(self, sample_team_with_owner_member) -> None:
        row = self._row(sample_team_with_owner_member.team, [SKIPPED])

        assert row["scan_label"] == "Nothing scanned"
        assert row["assessed"] is False

    def test_a_clean_run_is_clean(self, sample_team_with_owner_member) -> None:
        row = self._row(sample_team_with_owner_member.team, [CLEAN])

        assert row["scan_label"] == "Scanned"
        assert row["assessed"] is True
        assert row["vulnerabilities"] == 0

    def test_findings_outrank_everything(self, sample_team_with_owner_member) -> None:
        """A skipped provider must not hide another provider's vulnerability."""
        result = {"findings": [{"id": "CVE-2026-0001", "severity": "high", "component": {"name": "pkg"}}]}
        row = self._row(sample_team_with_owner_member.team, [SKIPPED, result])

        assert row["assessed"] is True
        assert row["scan_label"] == "Scanned"
        assert row["counts"]["high"] == 1


@pytest.mark.django_db
class TestOnlyWhenEveryProviderSkipped:
    """One scanner failing while another scanned the same artifact still leaves
    a real verdict. Calling that "nothing scanned" would be its own kind of
    wrong, and would hide a scan that did work."""

    def _counts(self, component_id: str, sbom_id: str) -> dict[str, Any] | None:
        from sbomify.apps.sboms.services.sboms_table import _attach_vulnerability_counts

        items = [{"sbom": {"id": sbom_id}}]
        _attach_vulnerability_counts(items, component_id, merged=True)
        return items[0]["vuln"]

    @pytest.fixture
    def sbom(self, sample_team_with_owner_member):  # noqa: F811
        from sbomify.apps.core.models import Component
        from sbomify.apps.sboms.models import SBOM

        component = Component.objects.create(name="Mixed Providers", team=sample_team_with_owner_member.team)
        return SBOM.objects.create(name="s", component=component, format="cyclonedx", format_version="1.6")

    def _run(self, sbom, plugin_name: str, result: dict[str, Any]) -> None:
        """A row shaped like one the orchestrator writes.

        ``plugin_version``, ``plugin_config_hash`` and ``run_reason`` are not
        read by anything under test — ``create()`` does not run ``full_clean``,
        so leaving them out stores empty strings rather than raising. They are
        filled in anyway so the fixture looks like production data and a later
        test reading them is not surprised by a blank.
        """
        from sbomify.apps.plugins.models import AssessmentRun
        from sbomify.apps.plugins.sdk.enums import RunReason, RunStatus

        AssessmentRun.objects.create(
            sbom=sbom,
            plugin_name=plugin_name,
            plugin_version="1.0.0",
            plugin_config_hash="test-config-hash",
            run_reason=RunReason.MANUAL,
            category="security",
            status=RunStatus.COMPLETED.value,
            result=result,
        )

    def test_both_skipped_is_nothing_scanned(self, sbom) -> None:
        self._run(sbom, "dependency-track", SKIPPED)
        self._run(sbom, "osv", SKIPPED)

        assert self._counts(sbom.component.id, sbom.id)["scanned_nothing"] is True

    def test_one_skipped_one_scanned_is_not(self, sbom) -> None:
        self._run(sbom, "dependency-track", SKIPPED)
        self._run(sbom, "osv", CLEAN)

        assert self._counts(sbom.component.id, sbom.id)["scanned_nothing"] is False

    def test_no_runs_at_all_stays_none(self, sbom) -> None:
        """Distinct from both: the table reads this as "Not scanned"."""
        assert self._counts(sbom.component.id, sbom.id) is None
