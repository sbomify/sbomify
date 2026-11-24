"""Guards for the fixes to the UI audit's High findings.

Each test names the finding it keeps fixed. Contrast is checked from the tokens
themselves, so a later palette change cannot quietly undo it.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.template import Context, Template
from django.template.loader import render_to_string

CSS = Path(settings.BASE_DIR) / "sbomify/assets/css/tailwind.src.css"


def _render(source: str, **context: object) -> str:
    return Template(source).render(Context(context))


# --- Date picker: keyboard users could not open it -----------------------------


def test_date_picker_is_a_labelled_native_date_input() -> None:
    html = _render(
        "{% include 'components/date_picker.html.j2' with value_binding='form.released_at' label='Released at' %}"
    )
    assert 'type="date"' in html
    assert re.search(r'<label[^>]*for="date-formreleased_at"', html)
    assert 'id="date-formreleased_at"' in html
    assert 'x-model.lazy="form.released_at"' in html
    # The hand-built calendar and its unnamed buttons are gone.
    assert "tw-calendar" not in html
    assert "prevMonth" not in html


def test_date_picker_with_time_uses_datetime_local() -> None:
    html = _render(
        "{% include 'components/date_picker.html.j2' with value_binding='form.created_at' include_time='true' %}"
    )
    assert 'type="datetime-local"' in html


def test_date_picker_without_a_label_is_still_named() -> None:
    html = _render(
        "{% include 'components/date_picker.html.j2' with value_binding='from' placeholder='Any date' compact='true' %}"
    )
    assert 'aria-label="Any date"' in html


# --- Tables: sideways scrolling hid the row's action on phones ------------------


def test_tables_stack_by_default_and_can_opt_out() -> None:
    html = render_to_string("core/cotton_probes/tables.html.j2")
    # Quote-aware: the fixed-layout class contains a ">" inside its value.
    tables = re.findall(r'<table\b(?:[^>"]|"[^"]*")*>', html)
    assert tables, "probe rendered no tables"
    side_by_side = [t for t in tables if 'aria-label="Side-by-side probe"' in t]
    assert side_by_side and "data-stack" not in side_by_side[0]
    assert all("data-stack" in t for t in tables if t not in side_by_side)


def test_stacked_table_rules_exist_and_beat_utilities() -> None:
    css = CSS.read_text()
    start = css.index("Stacked tables")
    block = css[start : css.index("\n/* ====", start)]
    assert "@media (max-width: 639.98px)" in block
    assert "content: attr(data-label)" in block
    # Unlayered, so the rules win over utility padding, borders and `hidden`.
    assert "@layer" not in block


# --- Delete dialog: its close button escaped to the viewport corner ----------


def test_delete_dialog_close_button_is_anchored_to_the_dialog() -> None:
    source = (Path(settings.BASE_DIR) / "sbomify/templates/components/modals/delete_modal.html.j2").read_text()
    wrapper, button = re.search(
        r'<div class="([^"]*)">\s*<c-buttons\.icon label="Close" class="([^"]*)"', source
    ).groups()
    assert "relative" in wrapper.split()
    assert "absolute" in button.split()


# --- Trust Center: a legacy rule turned panel titles into 24px headings ------


def test_legacy_stylesheet_no_longer_forces_heading_sizes() -> None:
    legacy = (Path(settings.BASE_DIR) / "sbomify/static/css/responsive.css").read_text()
    assert not re.search(r"\bh2\s*,\s*\.h2\s*\{\s*font-size:[^}]*!important", legacy)


# --- Contrast: primary buttons (dark) and status colours (light) --------------


def _tokens(css: str, start: str, end: str | None) -> dict[str, tuple[int, int, int]]:
    body = css[css.index(start) : css.index(end) if end else None]
    return {
        name: tuple(int(v) for v in rgb.split())
        for name, rgb in re.findall(r"--color-([a-z-]+):\s*rgb\((\d+ \d+ \d+)\)", body)
    }


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _tint(rgb: tuple[int, int, int], percent: int = 12) -> tuple[int, int, int]:
    return tuple(round(v * percent / 100 + 255 * (1 - percent / 100)) for v in rgb)


WHITE = (255, 255, 255)


@pytest.fixture(scope="module")
def themes() -> dict[str, dict[str, tuple[int, int, int]]]:
    css = CSS.read_text()
    # Anchored on the blocks themselves: comments above them mention ":root.light".
    dark = _tokens(css, "@theme {", "\n:root.light {")
    return {"dark": dark, "light": {**dark, **_tokens(css, "\n:root.light {", None)}}


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("token", ["primary-fill", "primary-fill-end", "primary-fill-hover", "primary-fill-hover-end"])
def test_white_text_on_filled_controls_meets_aa(themes, theme: str, token: str) -> None:
    assert _contrast(WHITE, themes[theme][token]) >= 4.5


@pytest.mark.parametrize("status", ["success", "warning", "danger", "info"])
def test_light_status_colours_read_as_text_and_on_their_badge_tint(themes, status: str) -> None:
    ink = themes["light"][status]
    assert _contrast(ink, WHITE) >= 4.5
    assert _contrast(ink, _tint(ink)) >= 4.5
