"""Verdicts on the artifact page's assessment tiles."""

import pytest

from sbomify.apps.plugins.services.assessment_scorecard import build_scorecards, scorecard_for_run


def _run(category: str = "compliance", status: str = "completed", **summary) -> dict:
    return {"category": category, "status": status, "result": {"summary": summary, "findings": [], "metadata": {}}}


@pytest.mark.parametrize(
    ("summary", "tone", "label", "caption"),
    [
        ({"pass_count": 6, "fail_count": 1, "total_findings": 7}, "warning", "1 issue", "6 of 7 checks passed"),
        ({"pass_count": 0, "fail_count": 2, "total_findings": 2}, "warning", "2 issues", "0 of 2 checks passed"),
        ({"pass_count": 1, "error_count": 1, "total_findings": 2}, "danger", "1 issue", "1 of 2 checks passed"),
        (
            {"pass_count": 0, "warning_count": 2, "total_findings": 2},
            "warning",
            "Warnings only",
            "0 of 2 checks passed",
        ),
        ({"pass_count": 3, "total_findings": 3}, "success", "Passed", "3 of 3 checks passed"),
    ],
)
def test_check_verdicts(summary, tone, label, caption):
    tile = scorecard_for_run(_run(**summary))
    assert (tile["tone"], tile["label"], tile["caption"]) == (tone, label, caption)


def test_a_scan_counts_severities_rather_than_findings():
    tile = scorecard_for_run(_run("security", by_severity={"critical": 1, "high": 2, "low": 1}, total_findings=9))
    assert tile["label"] == "4 vulnerabilities"
    assert tile["caption"] == "1 critical, 2 high"
    assert tile["bar_label"] == "1 critical, 2 high, 1 medium or low"


def test_a_clean_scan_passes():
    tile = scorecard_for_run(_run("security", by_severity={}))
    assert (tile["tone"], tile["label"]) == ("success", "No vulnerabilities")


def test_a_run_without_a_readable_result_claims_nothing():
    tile = scorecard_for_run({"category": "security", "status": "completed", "result": None})
    assert (tile["tone"], tile["label"]) == ("neutral", "No result")


def test_a_skipped_run_gives_its_reason():
    run = _run("security")
    run["result"]["metadata"] = {"skipped": True}
    run["result"]["findings"] = [{"title": "SPDX artifacts are not supported"}]
    tile = scorecard_for_run(run)
    assert (tile["label"], tile["caption"]) == ("Skipped", "SPDX artifacts are not supported")
    assert tile["segments"] == []


def test_zero_segments_are_dropped_from_the_bar():
    tile = scorecard_for_run(_run(pass_count=2, fail_count=0, warning_count=0, total_findings=2))
    assert tile["segments"] == [{"tone": "success", "count": 2, "one": "passed"}]
    assert tile["bar_label"] == "2 passed"


@pytest.mark.parametrize(
    ("warnings", "errors", "expected"),
    [(1, 1, "1 passed, 1 warning, 1 error"), (2, 3, "1 passed, 2 warnings, 3 errors")],
)
def test_the_written_breakdown_agrees_with_its_counts(warnings, errors, expected):
    """A screen reader hears this in place of the bar, so "1 warnings" is a bug."""
    tile = scorecard_for_run(
        _run(pass_count=1, warning_count=warnings, error_count=errors, total_findings=1 + warnings + errors)
    )
    assert tile["bar_label"] == expected


def test_a_clean_scan_says_so_rather_than_counting_a_segment():
    tile = scorecard_for_run(_run("security", by_severity={}))
    assert tile["bar_label"] == "No known vulnerabilities"


def test_tiles_lead_with_what_needs_attention():
    runs = {
        "latest_runs": [
            {**_run(pass_count=3, total_findings=3), "plugin_name": "passing"},
            {**_run(status="pending"), "plugin_name": "queued"},
            {**_run(pass_count=1, fail_count=1, total_findings=2), "plugin_name": "failing"},
        ],
        "unassessed_plugins": [{"plugin_name": "new"}],
    }
    order = [
        tile["run"]["plugin_name"] if tile["run"] else tile["plugin"]["plugin_name"] for tile in build_scorecards(runs)
    ]
    assert order == ["failing", "queued", "passing", "new"]
