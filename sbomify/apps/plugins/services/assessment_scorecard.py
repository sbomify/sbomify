"""The verdict on each assessment row of the artifact page.

Every scan, standard and not-yet-run plugin gets a row with a verdict ("2
issues", "4 vulnerabilities", "Skipped"), a one-line reason and a bar of its
outcomes, so a reader sees where each one stands without opening anything.

Verdicts mirror the rules in ``plugins/apis.py`` (``_is_run_failing`` and
``_is_run_skipped``) so a row never disagrees with the header badge above it.
"""

from typing import Any

from django.contrib.humanize.templatetags.humanize import intcomma

# Lower sorts first: what needs a decision leads, what needs nothing trails.
_RANK = {"danger": 0, "warning": 1, "info": 2, "success": 3, "neutral": 4}


def _count(summary: dict[str, Any], key: str) -> int:
    value = summary.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{intcomma(count)} {singular if count == 1 else plural}"


def _security_tile(summary: dict[str, Any]) -> dict[str, Any]:
    by_severity = summary.get("by_severity") or {}
    if not isinstance(by_severity, dict):
        by_severity = {}
    severities = {key: _count(by_severity, key) for key in ("critical", "high", "medium", "low")}
    other = sum(_count(by_severity, key) for key in by_severity if key not in severities)
    total = sum(severities.values()) + other
    if not by_severity and _count(summary, "error_count"):
        return {"tone": "danger", "label": "Could not scan", "caption": "The scanner reported an error."}
    if not total:
        return {
            "tone": "success",
            "label": "No vulnerabilities",
            "caption": "The latest scan found none.",
            "segments": [{"tone": "success", "count": 1}],
            "bar_label": "No known vulnerabilities",
        }
    worst = [_plural(severities[key], key, key) for key in ("critical", "high") if severities[key]]
    return {
        "tone": "warning",
        "label": _plural(total, "vulnerability", "vulnerabilities"),
        "caption": ", ".join(worst) if worst else "None critical or high",
        "segments": [
            {"tone": "critical", "count": severities["critical"], "one": "critical"},
            {"tone": "high", "count": severities["high"], "one": "high"},
            {"tone": "medium", "count": severities["medium"] + severities["low"], "one": "medium or low"},
            {"tone": "neutral", "count": other, "one": "unrated"},
        ],
    }


def _checks_tile(summary: dict[str, Any]) -> dict[str, Any]:
    passed = _count(summary, "pass_count")
    failed = _count(summary, "fail_count")
    errors = _count(summary, "error_count")
    warnings = _count(summary, "warning_count")
    total = _count(summary, "total_findings") or passed + failed + errors + warnings
    segments = [
        {"tone": "success", "count": passed, "one": "passed"},
        {"tone": "info", "count": warnings, "one": "warning", "many": "warnings"},
        {"tone": "warning", "count": failed, "one": "failed"},
        {"tone": "danger", "count": errors, "one": "error", "many": "errors"},
    ]
    caption = f"{intcomma(passed)} of {_plural(total, 'check', 'checks')} passed"
    if failed or errors:
        tone = "danger" if errors and not failed else "warning"
        return {
            "tone": tone,
            "label": _plural(failed + errors, "issue", "issues"),
            "caption": caption,
            "segments": segments,
        }
    # A legacy summary has no pass_count key at all; present-and-zero means
    # the plugin only warned and so verified nothing.
    if "pass_count" in summary and not passed:
        return {"tone": "warning", "label": "Warnings only", "caption": caption, "segments": segments}
    return {"tone": "success", "label": "Passed", "caption": caption, "segments": segments}


def scorecard_for_run(run: dict[str, Any]) -> dict[str, Any]:
    """The verdict, reason and bar for one run, as its row renders them."""
    tile: dict[str, Any]
    status = run.get("status")
    result = run.get("result") or {}
    metadata = result.get("metadata") or {}
    if status == "running":
        tile = {"tone": "info", "label": "Running", "caption": "Results appear when the run finishes."}
    elif status == "pending":
        tile = {"tone": "info", "label": "Queued", "caption": "Waiting to start."}
    elif status == "failed":
        tile = {"tone": "danger", "label": "Could not run", "caption": run.get("error_message") or "The run failed."}
    elif not run.get("result"):
        # The API drops a result that fails schema validation; reading that as
        # a clean pass would claim a verdict nobody can see.
        tile = {"tone": "neutral", "label": "No result", "caption": "The result could not be read. Try a re-run."}
    elif isinstance(metadata, dict) and metadata.get("skipped"):
        findings = result.get("findings") or [{}]
        tile = {"tone": "neutral", "label": "Skipped", "caption": findings[0].get("title") or "Did not apply."}
    else:
        summary = result.get("summary") or {}
        tile = _security_tile(summary) if run.get("category") == "security" else _checks_tile(summary)
    segments = [segment for segment in tile.get("segments", []) if segment["count"]]
    return {
        **tile,
        "segments": segments,
        # The written breakdown a screen reader hears in place of the bar.
        "bar_label": tile.get("bar_label")
        or ", ".join(_plural(s["count"], s["one"], s.get("many", s["one"])) for s in segments),
    }


def build_scorecards(assessment_runs: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Every run and every enabled-but-unrun plugin, most urgent first."""
    if not assessment_runs:
        return []
    tiles = [{"run": run, "plugin": None, **scorecard_for_run(run)} for run in assessment_runs.get("latest_runs") or []]
    tiles += [
        {
            "run": None,
            "plugin": plugin,
            "tone": "neutral",
            "label": "Not assessed",
            "caption": "Has not run on this artifact yet.",
            "segments": [],
            "bar_label": "",
        }
        for plugin in assessment_runs.get("unassessed_plugins") or []
    ]
    return sorted(tiles, key=lambda tile: _RANK[tile["tone"]])
