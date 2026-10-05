"""Render contract for the table summaries that replace rows of badges.

A table cell holds one aggregate: a proportional bar, a headline number and a
written breakdown. These tests pin that the breakdown is written out, the parts
always add up to the total, and the Alpine variants bind the row's data rather
than rendering badges per item.
"""

import re

import pytest
from django.template.loader import render_to_string

from sbomify.apps.core.templatetags.utils import severity_breakdown, severity_unknown

COUNTS = {"total": 1234, "critical": 3, "high": 13, "medium": 1200, "low": 0}


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string("core/cotton_probes/table_summaries.html.j2", {"counts": COUNTS})


def _probe(rendered: str, name: str) -> str:
    start = rendered.index(f'data-probe="{name}"')
    return rendered[start : rendered.index('<div data-probe="', start + 1) if name != "assessments" else None]


def test_server_summary_writes_out_the_breakdown_worst_first(rendered: str) -> None:
    server = _probe(rendered, "server")
    assert ">1,234<" in server
    assert "3 critical, 13 high, 1,200 medium, 18 unknown" in server


def test_server_bar_has_a_segment_per_nonzero_level_and_no_badges(rendered: str) -> None:
    server = _probe(rendered, "server")
    assert re.findall(r"bg-severity-(\w+)", server) == ["critical", "high", "medium"]
    assert "flex-grow: 18" in server
    assert "data-level" not in server


def test_bound_summary_binds_the_rows_counts(rendered: str) -> None:
    bound = _probe(rendered, "bound")
    assert "return item.vuln || {}" in bound
    assert 'x-text="$number(counts.total || 0)"' in bound
    assert "data-level" not in bound


def test_assessment_summary_folds_runs_into_one_cell(rendered: str) -> None:
    assessments = _probe(rendered, "assessments")
    assert "((item.assessments) || {}).plugins" in assessments
    assert "data-status" not in assessments
    assert "fa-xmark" not in assessments
    assert "Not passed: " in assessments


@pytest.mark.parametrize(
    ("counts", "breakdown", "unknown"),
    [
        (None, "", 0),
        ({}, "", 0),
        ({"total": 0, "critical": 0}, "", 0),
        ({"total": 2, "low": 2}, "2 low", 0),
        ({"total": 5, "critical": None, "high": 2}, "2 high, 3 unknown", 3),
        ({"total": 1, "high": 2}, "2 high", 0),
    ],
)
def test_severity_filters(counts: dict | None, breakdown: str, unknown: int) -> None:
    assert severity_breakdown(counts) == breakdown
    assert severity_unknown(counts) == unknown
