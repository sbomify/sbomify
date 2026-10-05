"""Render contract for a version row's two answers.

c-vulnerabilities.open leads with what needs action (critical, high) and says
what the version introduced; c-assessments.compliance names the first check
that failed and links to it. Neither renders a badge per item, and neither
calls a state clean that it cannot stand behind.
"""

import re

import pytest
from django.template.loader import render_to_string
from django.utils.html import strip_tags

VULNERABILITIES = [
    ("open", {"state": "open", "critical": 3, "high": 1300, "other": 11, "new": 2}),
    ("high-only", {"state": "open", "critical": 0, "high": 1, "other": 0, "new": None}),
    ("other-only", {"state": "open", "critical": 0, "high": 0, "other": 4, "new": 1}),
    ("none", {"state": "none"}),
    ("nothing-scanned", {"state": "nothing_scanned"}),
    ("not-scanned", {"state": "not_scanned"}),
    ("not-applicable", {"state": "not_applicable"}),
]
COMPLIANCE = [
    ("fails", {"state": "fails", "first": "BSI TR-03183-2", "more": 5}),
    ("fails-one", {"state": "fails", "first": "NTIA", "more": 0}),
    ("error", {"state": "error", "first": "GitHub Attestation", "more": 0}),
    ("checking", {"state": "checking"}),
    ("meets", {"state": "meets", "total": 3}),
    ("none", {"state": "none"}),
]


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string(
        "core/cotton_probes/version_summaries.html.j2",
        {"vulnerabilities": VULNERABILITIES, "compliance": COMPLIANCE},
    )


def _probe(rendered: str, name: str) -> str:
    start = rendered.index(f'data-probe="{name}"')
    end = rendered.find('<div data-probe="', start + 1)
    return rendered[start : end if end != -1 else None]


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", strip_tags(fragment.split(">", 1)[1])).strip()


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("vuln-open", "3 critical, 1,300 high 2 new · 11 other"),
        ("vuln-high-only", "1 high"),
        ("vuln-other-only", "4 other 1 new"),
        ("vuln-none", "None open"),
        ("vuln-nothing-scanned", "Nothing scanned"),
        ("vuln-not-scanned", "Not scanned"),
        ("vuln-not-applicable", "—"),
        ("compliance-fails", "Fails BSI TR-03183-2 and 5 more"),
        ("compliance-fails-one", "Fails NTIA"),
        ("compliance-error", "Could not check GitHub Attestation"),
        ("compliance-checking", "Checking"),
        ("compliance-meets", "Meets all 3"),
        ("compliance-none", "—"),
    ],
)
def test_each_state_reads_as_one_sentence(rendered: str, name: str, text: str) -> None:
    assert _text(_probe(rendered, name)) == text


def test_only_critical_and_high_carry_severity_ink_and_nothing_is_a_badge(rendered: str) -> None:
    fragment = _probe(rendered, "vuln-open")
    assert re.findall(r"text-severity-(\w+)", fragment) == ["critical", "high"]
    assert "data-level" not in fragment
    assert "text-severity" not in _probe(rendered, "vuln-other-only")


def test_a_clean_tone_is_only_for_a_real_scan(rendered: str) -> None:
    assert "bg-success" in _probe(rendered, "vuln-none")
    for state in ("nothing-scanned", "not-scanned", "not-applicable"):
        assert "bg-success" not in _probe(rendered, f"vuln-{state}")
    assert "bg-success" not in _probe(rendered, "compliance-error")


def test_the_failing_check_links_to_the_version(rendered: str) -> None:
    assert '<a href="/component/x/sboms/y/"' in _probe(rendered, "compliance-fails")
    assert "<a " not in _probe(rendered, "compliance-meets")


def test_bound_variant_reads_the_row_and_leaves_the_comma_its_own_space(rendered: str) -> None:
    bound = _probe(rendered, "vuln-bound")
    assert "return item.vuln" in bound
    assert ",&nbsp;" in bound
    assert "inline-flex" in bound
