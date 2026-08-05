"""EPSS capture and CVSS 4.0 support across both scanner paths.

Two prioritisation signals were being dropped: the OSV parser returned None for
any `CVSS:4.0` vector, and the Dependency Track converter read only the v3/v2
base scores, so EPSS and the publish timestamps never left the payload.
"""

from __future__ import annotations

import pytest

from sbomify.apps.plugins.builtins.dependency_track import DependencyTrackPlugin, _first_float
from sbomify.apps.plugins.builtins.osv import OSVPlugin

CVSS3 = "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H"  # S:C -> 10.0, v4 gives 9.0
CVSS4 = "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"


class TestFirstFloat:
    def test_takes_the_first_real_number(self):
        assert _first_float(None, "", 7.5) == 7.5

    def test_coerces_a_string(self):
        assert _first_float("9.8") == 9.8

    def test_zero_is_a_value_not_a_miss(self):
        """0.0 is a legitimate EPSS score, so `or` chaining would drop it."""
        assert _first_float(0.0, 9.9) == 0.0

    def test_booleans_are_not_numbers(self):
        assert _first_float(True, 4.0) == 4.0

    def test_all_missing_is_none(self):
        assert _first_float(None, "not a number") is None


class TestOsvCvss4:
    @pytest.fixture
    def plugin(self):
        return OSVPlugin(config={})

    def test_a_v4_vector_now_scores(self, plugin):
        """It returned None before, so a v4-only advisory scored nothing."""
        assert plugin._extract_cvss_score(CVSS4) == 9.0

    def test_a_v3_vector_still_scores(self, plugin):
        assert plugin._extract_cvss_score(CVSS3) == 10.0

    def test_v4_impact_metrics_are_the_renamed_ones(self, plugin):
        """CVSS 4.0 uses VC/VI/VA, so the v3 substrings never match."""
        low = "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:L/VI:N/VA:N/SC:N/SI:N/SA:N"

        assert plugin._extract_cvss_score(low) == 4.0

    def test_a_foreign_vector_is_still_rejected(self, plugin):
        assert plugin._extract_cvss_score("CVSS:2.0/AV:N/AC:L/Au:N/C:P/I:P/A:P") is None

    def test_v3_is_preferred_when_a_record_carries_both(self, plugin):
        """Keeps a finding's score stable across a rescan once OSV adds a v4
        entry to a record that already had v3."""
        vuln = {
            "severity": [
                {"type": "CVSS_V4", "score": CVSS4},
                {"type": "CVSS_V3", "score": CVSS3},
            ]
        }

        _, score = plugin._map_severity(vuln)

        assert score == 10.0

    def test_v4_alone_is_used(self, plugin):
        vuln = {"severity": [{"type": "CVSS_V4", "score": CVSS4}]}

        severity, score = plugin._map_severity(vuln)

        assert score == 9.0
        assert severity == "critical"


class TestDependencyTrackCapture:
    @pytest.fixture
    def plugin(self):
        return DependencyTrackPlugin(config={})

    @staticmethod
    def _payload(**vuln) -> list[dict]:
        base = {"vulnId": "CVE-2021-44228", "severity": "CRITICAL", "description": "rce"}
        return [{"vulnerability": {**base, **vuln}, "component": {"name": "log4j-core", "version": "2.14.1"}}]

    def test_epss_is_captured(self, plugin):
        findings = plugin._convert_dt_findings(self._payload(epssScore=0.97, epssPercentile=0.999))

        assert findings[0].epss_score == 0.97
        assert findings[0].epss_percentile == 0.999

    def test_timestamps_are_captured(self, plugin):
        """Finding age could never render for a DT finding without these."""
        findings = plugin._convert_dt_findings(
            self._payload(published="2021-12-10T00:00:00Z", updated="2021-12-14T00:00:00Z")
        )

        assert findings[0].published_at == "2021-12-10T00:00:00Z"
        assert findings[0].modified_at == "2021-12-14T00:00:00Z"

    def test_cvss_v4_is_accepted(self, plugin):
        findings = plugin._convert_dt_findings(self._payload(cvssV4BaseScore=9.3))

        assert findings[0].cvss_score == 9.3

    def test_v3_wins_over_v4_and_v2(self, plugin):
        findings = plugin._convert_dt_findings(
            self._payload(cvssV3BaseScore=10.0, cvssV4BaseScore=9.3, cvssV2BaseScore=7.5)
        )

        assert findings[0].cvss_score == 10.0

    def test_v2_is_still_the_last_resort(self, plugin):
        findings = plugin._convert_dt_findings(self._payload(cvssV2BaseScore=7.5))

        assert findings[0].cvss_score == 7.5

    def test_absent_signals_stay_none(self, plugin):
        findings = plugin._convert_dt_findings(self._payload())

        assert findings[0].epss_score is None
        assert findings[0].cvss_score is None
        assert findings[0].published_at is None
