"""The overview's two panels each show a slice. Each has to say so.

Both panels render a capped list beside a metric counting something larger, so
a reader who compares the two and finds them disagreeing has no way to tell a
cap from a bug. These render the components directly: the numbers under test
are the ones the templates print, not the ones the service computed.
"""

from typing import Any

from django.template.loader import render_to_string
from django.utils.html import strip_tags


def text_of(template: str, context: dict[str, Any]) -> str:
    return " ".join(strip_tags(render_to_string(template, context)).split())


def finding(advisory: str) -> dict[str, Any]:
    return {
        "id": advisory,
        "component_id": "comp000000001",
        "component_name": "Example component",
        "package": "libexample",
        "version": "1.0.0",
        "severity": "high",
        "kev": False,
        "malicious": False,
        "decision": "Not reviewed",
        "products": ["Example product"],
        "sla": {"overdue": False, "label": "12 days left"},
    }


def priority_text(shown: int, total: int) -> str:
    return text_of(
        "components/overview/priority.html",
        {
            "dashboard": {
                "needs_attention": [finding(f"CVE-2026-1000{index}") for index in range(shown)],
                "needs_attention_total": total,
                "metrics": {"open": total},
            },
            "workspace_key": "",
        },
    )


def product(name: str, **overrides: Any) -> dict[str, Any]:
    row = {
        "id": "prod00000001",
        "name": name,
        "component_count": 2,
        "security_component_count": 2,
        "counts": {"total": 3, "critical": 1, "high": 1, "medium": 1, "low": 0, "other": 1, "unknown": 0},
        "unassessed": 0,
        "stale": 0,
        "missing_sboms": 0,
        "no_policy": 0,
        "past_sla": 0,
    }
    row.update(overrides)
    return row


def exposure_text(rows: list[dict[str, Any]], product_count: int) -> str:
    return text_of("components/overview/products.html", {"products": rows, "product_count": product_count})


def test_the_digest_says_how_much_of_the_list_it_is_showing() -> None:
    assert "Top 4 of 37, ranked by exploitation and patch SLA" in priority_text(shown=4, total=37)


def test_a_digest_that_is_the_whole_list_says_nothing_about_a_count() -> None:
    whole = priority_text(shown=3, total=3)
    assert "Ranked by exploitation and patch SLA" in whole
    assert "of 3" not in whole


def test_exposure_says_its_counts_do_not_add_up_and_why() -> None:
    note = exposure_text([product("Example product")], product_count=1)
    assert "do not add up to the workspace total" in note
    assert "counts in every product that has it" in note
    assert "is not listed" in note


def test_exposure_says_how_many_products_it_left_out() -> None:
    rows = [product(f"Product {index}") for index in range(8)]
    assert "Showing 8 of 12 products." in exposure_text(rows, product_count=12)
    assert "Showing" not in exposure_text(rows, product_count=8)


def test_a_product_with_nothing_scannable_says_so_once() -> None:
    """The row used to print the same words in two columns under two
    treatments: a pill in Vulnerabilities and a status dot in Evidence."""
    row = exposure_text([product("Empty product", component_count=0, security_component_count=0)], 1)
    assert row.count("No components") == 1
    assert "Not applicable" in row


def test_the_past_sla_column_keeps_one_shape_at_zero() -> None:
    """A danger pill above zero and bare text at zero made the column alternate
    between a pill and a floating digit down its length."""
    html = render_to_string(
        "components/overview/products.html",
        {"products": [product("Breached", past_sla=3), product("Clean", past_sla=0)], "product_count": 2},
    )
    assert 'class="text-xs tabular-nums font-semibold text-danger">3<' in html
    assert 'class="text-xs tabular-nums text-text-muted">0<' in html
