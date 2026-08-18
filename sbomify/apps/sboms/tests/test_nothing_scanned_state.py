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


class TestTheRowStatus:
    """The product page's single filterable status per component."""

    def _status(self, vuln: dict[str, Any] | None) -> str:
        from sbomify.apps.core.services.product_page import _row_status

        return _row_status(vuln)

    def test_no_run_is_not_scanned(self) -> None:
        assert self._status(None) == "not_scanned"

    def test_a_skipped_run_is_its_own_state(self) -> None:
        counts = {"total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "scanned_nothing": True}

        assert self._status(counts) == "scanned_nothing"

    def test_a_clean_run_is_clean(self) -> None:
        counts = {"total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "scanned_nothing": False}

        assert self._status(counts) == "clean"

    def test_findings_outrank_everything(self) -> None:
        """A skipped provider alongside one that found something must not hide
        the finding — severity wins."""
        counts = {"total": 1, "critical": 0, "high": 1, "medium": 0, "low": 0, "scanned_nothing": True}

        assert self._status(counts) == "high"


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
