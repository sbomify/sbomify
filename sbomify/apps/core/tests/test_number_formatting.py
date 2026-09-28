"""Display grouping must not leak into links, chart geometry or pagination state."""

import pytest
from django.core.paginator import Paginator
from django.template.loader import render_to_string


def test_shared_counts_are_grouped_without_changing_machine_values() -> None:
    html = render_to_string(
        "core/cotton_probes/number_formatting.html.j2",
        {
            "value": 12345678,
            "pages": [999, 1000, "…", 2000],
            "counts": {"total": 12345, "critical": 1234, "high": 2345, "other": 8766},
            "inventory": {
                "page": Paginator(range(12345), 25).page(41),
                "page_range": [40, 41, 42],
                "base_url": "/products/",
                "query": "sort=name",
            },
        },
    )
    assert "12,345,678" in html
    assert ">1,000</span>" in html
    assert ">2,000</a>" in html
    assert 'href="/products/?page=2000&amp;sort=name"' in html
    assert "12,345 open occurrences: 1,234 critical, 2,345 high, 8,766 other" in html
    assert "flex-grow: 1234" in html
    assert "flex-grow: 1,234" not in html
    assert "Showing 1,001 to 1,025 of 12,345" in html


@pytest.mark.parametrize(
    "value,expected",
    [(0, "0"), (999, "999"), (1000, "1,000"), ("1234.50", "1,234.50"), ("96%", "96%"), ("—", "—"), ("1,234", "1,234")],
)
def test_stat_card_preserves_zero_decimals_and_formatted_labels(value: int | str, expected: str) -> None:
    html = render_to_string("core/cotton_probes/number_formatting.html.j2", {"value": value})
    value_html = html.split("<dd", 1)[1].split("</dd>", 1)[0].split(">", 1)[1].strip()
    assert value_html == expected
