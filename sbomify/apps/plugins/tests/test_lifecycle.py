"""Vulnerability lifecycle: first-seen, resolved, age and MTTR.

Most of these guard one rule: **absent from a scan does not mean fixed**. The
naive reading marks a component remediated exactly when scanning breaks, which
makes MTTR look best at the worst moment.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from sbomify.apps.plugins.lifecycle import record_run, run_scanned
from sbomify.apps.plugins.models import AssessmentRun, VulnerabilityLifecycle

pytestmark = pytest.mark.django_db


def _result(*advisory_ids, skipped: bool = False, severity: str = "high") -> dict:
    findings = [{"id": aid, "severity": severity} for aid in advisory_ids]
    result: dict = {"summary": {"total_findings": len(findings)}, "findings": findings}
    if skipped:
        result["metadata"] = {"skipped": True}
    return result


def _run(sbom, *, plugin: str = "osv", status: str = "completed", **kwargs) -> AssessmentRun:
    return AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin,
        plugin_version="1.0.0",
        category="security",
        status=status,
        result=_result(**kwargs) if "advisory_ids" not in kwargs else None,
    )


def _scan(sbom, *advisory_ids, plugin: str = "osv", status: str = "completed", skipped: bool = False):
    run = AssessmentRun.objects.create(
        sbom=sbom,
        plugin_name=plugin,
        plugin_version="1.0.0",
        category="security",
        status=status,
        result=_result(*advisory_ids, skipped=skipped),
    )
    return record_run(run)


class TestEvidence:
    def test_a_completed_scan_carries_evidence(self, sample_sbom):
        run = _run(sample_sbom)

        assert run_scanned(run) is True

    def test_a_skipped_run_carries_none(self, sample_sbom):
        """Dependency Track handed an SPDX SBOM returns exactly this."""
        run = AssessmentRun.objects.create(
            sbom=sample_sbom,
            plugin_name="dependency-track",
            plugin_version="1.0.0",
            category="security",
            status="completed",
            result=_result(skipped=True),
        )

        assert run_scanned(run) is False

    def test_a_failed_run_carries_none(self, sample_sbom):
        run = AssessmentRun.objects.create(
            sbom=sample_sbom, plugin_name="osv", plugin_version="1.0.0", category="security", status="failed"
        )

        assert run_scanned(run) is False


class TestOpening:
    def test_a_first_sighting_opens_a_row(self, sample_sbom, sample_component):
        counts = _scan(sample_sbom, "CVE-2021-44228")

        assert counts["opened"] == 1
        row = VulnerabilityLifecycle.objects.get(advisory_id="CVE-2021-44228")
        assert row.is_open is True
        assert row.first_seen_at == row.last_seen_at

    def test_a_second_sighting_does_not_restart_the_clock(self, sample_sbom):
        """first_seen_at is the point of the table; a rescan must not reset it."""
        _scan(sample_sbom, "CVE-2021-44228")
        first_seen = VulnerabilityLifecycle.objects.get().first_seen_at

        counts = _scan(sample_sbom, "CVE-2021-44228")

        row = VulnerabilityLifecycle.objects.get()
        assert counts["seen"] == 1
        assert row.first_seen_at == first_seen
        assert row.last_seen_at >= first_seen

    def test_the_key_is_the_component_not_the_sbom(self, sample_sbom, sample_component):
        """A component publishes many SBOMs and the same CVE persists across
        them; keying per SBOM would make every finding look a day old."""
        from sbomify.apps.sboms.models import SBOM

        second = SBOM.objects.create(
            component=sample_component, name="v2", version="2.0", format="cyclonedx", bom_type="sbom"
        )
        _scan(sample_sbom, "CVE-2021-44228")
        first_seen = VulnerabilityLifecycle.objects.get().first_seen_at

        _scan(second, "CVE-2021-44228")

        assert VulnerabilityLifecycle.objects.count() == 1
        assert VulnerabilityLifecycle.objects.get().first_seen_at == first_seen


class TestResolution:
    def test_a_scan_that_ran_closes_what_it_no_longer_reports(self, sample_sbom):
        _scan(sample_sbom, "CVE-2021-44228", "CVE-2021-45046")

        counts = _scan(sample_sbom, "CVE-2021-44228")

        assert counts["resolved"] == 1
        assert VulnerabilityLifecycle.objects.get(advisory_id="CVE-2021-45046").is_open is False
        assert VulnerabilityLifecycle.objects.get(advisory_id="CVE-2021-44228").is_open is True

    def test_a_skipped_run_resolves_nothing(self, sample_sbom):
        """The trap. Dependency Track handed an SPDX SBOM drops every finding
        at once; the naive rule would mark the component fully remediated."""
        _scan(sample_sbom, "CVE-2021-44228", plugin="dependency-track")

        counts = _scan(sample_sbom, plugin="dependency-track", skipped=True)

        assert counts == {"opened": 0, "seen": 0, "resolved": 0}
        assert VulnerabilityLifecycle.objects.get().is_open is True

    def test_a_failed_run_resolves_nothing(self, sample_sbom):
        _scan(sample_sbom, "CVE-2021-44228")

        counts = _scan(sample_sbom, status="failed")

        assert counts["resolved"] == 0
        assert VulnerabilityLifecycle.objects.get().is_open is True

    def test_one_scanner_does_not_close_another_scanners_findings(self, sample_sbom):
        """OSV and Dependency Track see different things."""
        _scan(sample_sbom, "CVE-2021-44228", plugin="dependency-track")

        _scan(sample_sbom, "CVE-2021-45046", plugin="osv")

        assert VulnerabilityLifecycle.objects.get(advisory_id="CVE-2021-44228").is_open is True

    def test_a_finding_a_peer_still_reports_stays_open(self, sample_sbom):
        """Both saw it and only OSV stopped, so the component still has it.

        The harder half of the rule above: OSV had reported this one, so "did
        my plugin ever see it" is not enough to license closing it.
        """
        _scan(sample_sbom, "CVE-2021-44228", plugin="dependency-track")
        _scan(sample_sbom, "CVE-2021-44228", plugin="osv")

        counts = _scan(sample_sbom, plugin="osv")

        assert counts["resolved"] == 0
        assert VulnerabilityLifecycle.objects.get().is_open is True

    def test_a_peers_skipped_run_does_not_erase_its_earlier_evidence(self, sample_sbom):
        """Dependency Track handed an SPDX SBOM reports nothing, which is not DT
        saying the finding went away."""
        _scan(sample_sbom, "CVE-2021-44228", plugin="dependency-track")
        _scan(sample_sbom, "CVE-2021-44228", plugin="osv")
        _scan(sample_sbom, plugin="dependency-track", skipped=True)

        counts = _scan(sample_sbom, plugin="osv")

        assert counts["resolved"] == 0
        assert VulnerabilityLifecycle.objects.get().is_open is True

    def test_it_resolves_once_the_last_scanner_stops_reporting_it(self, sample_sbom):
        _scan(sample_sbom, "CVE-2021-44228", plugin="dependency-track")
        _scan(sample_sbom, "CVE-2021-44228", plugin="osv")
        _scan(sample_sbom, plugin="osv")

        counts = _scan(sample_sbom, plugin="dependency-track")

        assert counts["resolved"] == 1
        assert VulnerabilityLifecycle.objects.get().is_open is False

    def test_a_returning_finding_reopens_rather_than_duplicating(self, sample_sbom):
        _scan(sample_sbom, "CVE-2021-44228")
        _scan(sample_sbom)
        assert VulnerabilityLifecycle.objects.get().is_open is False

        _scan(sample_sbom, "CVE-2021-44228")

        assert VulnerabilityLifecycle.objects.count() == 1
        assert VulnerabilityLifecycle.objects.get().is_open is True


class TestMetrics:
    def test_age_counts_from_first_sighting_while_open(self, sample_sbom):
        _scan(sample_sbom, "CVE-2021-44228")
        row = VulnerabilityLifecycle.objects.get()
        VulnerabilityLifecycle.objects.filter(pk=row.pk).update(
            first_seen_at=timezone.now() - timedelta(days=45)
        )

        assert VulnerabilityLifecycle.objects.get().age_days == 45

    def test_age_stops_at_resolution_which_is_the_mttr(self, sample_sbom):
        _scan(sample_sbom, "CVE-2021-44228")
        row = VulnerabilityLifecycle.objects.get()
        now = timezone.now()
        VulnerabilityLifecycle.objects.filter(pk=row.pk).update(
            first_seen_at=now - timedelta(days=100), resolved_at=now - timedelta(days=70)
        )

        assert VulnerabilityLifecycle.objects.get().age_days == 30


class TestNonVulnerabilities:
    def test_operational_findings_do_not_open_rows(self, sample_sbom):
        """A scanner's own bookkeeping is not a vulnerability with a lifetime."""
        _scan(sample_sbom, "dependency-track:unsupported-format")

        assert VulnerabilityLifecycle.objects.count() == 0
