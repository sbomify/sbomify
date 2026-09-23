"""Production stat-card callers must preserve filtered and formatted counts."""

import re
from typing import Any

import pytest
from django.template.loader import render_to_string
from django.utils.html import strip_tags


def stat_values(template: str, context: dict[str, Any]) -> dict[str, str]:
    html = render_to_string(template, context)
    return {
        " ".join(strip_tags(label).split()): " ".join(strip_tags(value).split())
        for label, value in re.findall(r"<dt\b[^>]*>(.*?)</dt>\s*<dd\b[^>]*>(.*?)</dd>", html, re.S)
    }


def test_trend_stats_keep_formatted_counts() -> None:
    values = stat_values(
        "vulnerability_scanning/components/_vulnerability_trends_body.html.j2",
        {"has_data": True, "summary": {"total": 1234, "critical": 12, "high": 34, "medium": 1188, "low": 0}},
    )
    assert values == {"Total": "1,234", "Critical": "12", "High": "34", "Medium": "1,188", "Low": "0"}


def test_crypto_posture_stats_keep_counts_and_default_missing_counts_to_zero() -> None:
    values = stat_values(
        "sboms/components/crypto_posture_card.html.j2",
        {
            "component_id": "component123",
            "sbom_id": "artifact1234",
            "posture": {"pqc_counts": {"quantum_vulnerable": 2, "quantum_safe": 1}},
        },
    )
    assert values == {"Vulnerable": "2", "Review": "0", "Quantum-safe": "1"}


@pytest.mark.parametrize("skipped", [False, True])
def test_security_assessment_stats_keep_severity_counts_and_skip_marker_out_of_total(skipped: bool) -> None:
    values = stat_values(
        "plugins/components/_assessment_run_item.html.j2",
        {
            "loop_index": 1,
            "run": {
                "id": "run1",
                "plugin_name": "osv",
                "category": "security",
                "status": "completed",
                "result": {
                    "metadata": {"skipped": skipped},
                    "summary": {"by_severity": {"critical": 2, "high": 3, "low": 1}},
                },
            },
        },
    )
    assert values == {"Critical": "2", "High": "3", "Medium": "0", "Low": "1", "Total": "0" if skipped else "6"}


def test_compliance_assessment_stats_keep_nonzero_counts() -> None:
    values = stat_values(
        "plugins/components/_assessment_run_item.html.j2",
        {
            "loop_index": 1,
            "run": {
                "id": "run1",
                "plugin_name": "ntia",
                "category": "compliance",
                "status": "completed",
                "result": {"summary": {"pass_count": 8, "fail_count": 2, "warning_count": 1, "total_findings": 11}},
            },
        },
    )
    assert values == {"Pass": "8", "Fail": "2", "Error": "0", "Warn": "1", "Info": "0", "Total": "11"}
