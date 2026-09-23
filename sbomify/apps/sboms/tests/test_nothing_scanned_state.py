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


@pytest.mark.django_db
class TestTheSbomPages:
    """The same three states on the SBOM's own pages.

    Both told you to wait: the scan report said "No Scan Data Available, try
    again later" and the assessment card said "Pending". Waiting helps with
    "Not scanned" alone. A skip repeats until someone fixes its reason, and a
    clean scan has finished.
    """

    NO_PACKAGES = "None of the packages in this SBOM could be matched against an advisory source."
    NO_PRODUCT = "Dependency Track only scans components that belong to a product."

    def _run(self, sbom, plugin_name: str, result: dict[str, Any] | None) -> None:
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

    def _skipped(self, finding_id: str, description: str) -> dict[str, Any]:
        finding = {"id": finding_id, "title": "Skipped", "description": description, "status": "warning"}
        return {**SKIPPED, "findings": [finding]}

    def _open(self, sbom, url: str | None = None):
        """The scan report unless ``url`` names another page."""
        from django.test import Client
        from django.urls import reverse

        from sbomify.apps.sboms.tests.test_views import setup_test_session

        client = Client()
        setup_test_session(client, sbom.component.team, sbom.component.team.members.first())
        response = client.get(url or reverse("sboms:sbom_vulnerabilities", kwargs={"sbom_id": sbom.id}))
        assert response.status_code == 200
        return response

    def test_every_provider_skipped_says_why(self, sample_sbom) -> None:
        self._run(sample_sbom, "osv", self._skipped("osv:no-packages", self.NO_PACKAGES))
        self._run(sample_sbom, "dependency-track", self._skipped("dependency-track:no-product", self.NO_PRODUCT))

        response = self._open(sample_sbom)
        html = response.content.decode()

        assert "Nothing scanned" in html
        assert self.NO_PACKAGES in html
        assert self.NO_PRODUCT in html
        assert "No Scan Data Available" not in html
        # Nothing was scanned, so there is no scan to date.
        assert response.context["scan_timestamp"] is None

    def test_a_clean_scan_says_nothing_was_found(self, sample_sbom) -> None:
        self._run(sample_sbom, "osv", CLEAN)

        html = self._open(sample_sbom).content.decode()

        assert "No vulnerabilities found" in html
        assert "No Scan Data Available" not in html
        assert "Nothing scanned" not in html

    def test_a_run_with_no_result_is_not_a_clean_scan(self, sample_sbom) -> None:
        """The column is nullable. A run that came back with nothing examined
        nothing, so it cannot vouch for the SBOM."""
        self._run(sample_sbom, "osv", None)

        html = self._open(sample_sbom).content.decode()

        assert "No vulnerabilities found" not in html
        assert "No Scan Data Available" in html

    def test_no_runs_at_all_still_has_no_data(self, sample_sbom) -> None:
        html = self._open(sample_sbom).content.decode()

        assert "No Scan Data Available" in html
        assert "Nothing scanned" not in html

    def test_one_skipped_one_clean_is_clean(self, sample_sbom) -> None:
        self._run(sample_sbom, "dependency-track", self._skipped("dependency-track:no-product", self.NO_PRODUCT))
        self._run(sample_sbom, "osv", CLEAN)

        html = self._open(sample_sbom).content.decode()

        assert "No vulnerabilities found" in html
        assert "Nothing scanned" not in html

    def test_the_assessment_card_says_skipped_not_pending(self, sample_sbom) -> None:
        from django.urls import reverse

        self._run(sample_sbom, "osv", self._skipped("osv:no-packages", self.NO_PACKAGES))
        url = reverse(
            "core:component_item",
            kwargs={"component_id": sample_sbom.component.id, "item_type": "sboms", "item_id": sample_sbom.id},
        )

        html = self._open(sample_sbom, url).content.decode()

        # "Skipped" and "Pending" both appear elsewhere on this page (the run
        # cards, a zero count), so match the card header's own markup.
        assert '<i class="fas fa-ban"></i>Skipped' in html
        assert '<i class="fas fa-clock"></i>Pending' not in html
