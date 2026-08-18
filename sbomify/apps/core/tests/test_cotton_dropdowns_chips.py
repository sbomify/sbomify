"""Render contract for the cotton dropdowns and chips component sets.

The probe template exercises every component in components/dropdowns and
components/chips; these tests pin the panel's surface and menu semantics, the
item recipes and their polymorphic branches, and the size and accent segments
of both chips, so pages can rely on the components without ever writing a class
themselves.
"""

import re

import pytest
from django.template.loader import render_to_string

PANEL = "min-w-48"
ITEM = "group flex items-center gap-3"
ICON_CHIP = "shrink-0 flex items-center justify-center"
METRIC_CHIP = "inline-flex items-center gap-1.5"
ASSESSMENT = "inline-flex items-center justify-center gap-1"


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string("core/cotton_probes/dropdowns_chips.html.j2")


def _classes(rendered: str, prefix: str, marker: str) -> str:
    """The class list of the element whose classes start with prefix and which holds marker."""
    marker_at = rendered.index(marker)
    start = rendered.rindex(prefix, 0, marker_at)
    return rendered[start : rendered.index('"', start)]


def _opening(rendered: str, prefix: str, marker: str) -> str:
    """Everything from that element's tag up to marker: its attributes, and nothing after them."""
    marker_at = rendered.index(marker)
    class_at = rendered.rindex(prefix, 0, marker_at)
    return rendered[rendered.rindex("<", 0, class_at) : marker_at]


def _item_opening(rendered: str, marker: str) -> str:
    return _opening(rendered, ITEM, marker)


# ── The panel ────────────────────────────────────────────────────────────────


def test_panel_carries_the_shared_surface(rendered: str) -> None:
    panel = _classes(rendered, PANEL, "Component actions")
    for bit in (
        "min-w-48",
        "bg-surface",
        "rounded-xl",
        "border border-solid border-border",
        "shadow-[0_10px_40px_-10px_rgb(0_0_0/0.3)]",
        "z-50",
        "origin-top",
        "animate-[scaleIn_0.15s_ease-out]",
    ):
        assert bit in panel


def test_default_panel_is_absolute_and_inset(rendered: str) -> None:
    panel = _classes(rendered, PANEL, "Component actions")
    assert "absolute p-1.5" in panel
    assert "fixed" not in panel
    assert "overflow" not in panel


def test_floating_panel_is_fixed_capped_and_scrolls(rendered: str) -> None:
    panel = _classes(rendered, PANEL, "Download")
    assert "fixed max-h-[min(70vh,32rem)] p-1.5 overflow-y-auto" in panel
    assert "absolute" not in panel


def test_flush_panel_drops_the_padding_and_owns_overflow(rendered: str) -> None:
    panel = _classes(rendered, PANEL, "SBOM uploaded")
    assert "absolute p-0 overflow-hidden" in panel
    assert "p-1.5" not in panel
    assert "overflow-y-auto" not in panel


def test_position_and_padding_segments_never_conflict(rendered: str) -> None:
    floating = _classes(rendered, PANEL, "Download")
    assert floating.count("p-1.5") == 1
    assert floating.count("overflow-") == 1
    assert floating.count("absolute") + floating.count("fixed") == 1


def test_menu_panel_carries_the_keyboard_handling(rendered: str) -> None:
    panel = _opening(rendered, PANEL, "Component actions")
    assert 'role="menu"' in panel
    assert 'aria-orientation="vertical"' in panel
    for key in ("arrow-down", "arrow-up", "home", "end"):
        assert f"@keydown.{key}.prevent" in panel


def test_menu_keys_reach_a_choice_row_as_well_as_a_command(rendered: str) -> None:
    """A row that is a setting, not a command, is still stepped through.

    The keys match on the menuitem prefix, so menuitemradio and
    menuitemcheckbox rows are walked with the rest rather than skipped.
    """
    panel = _opening(rendered, PANEL, "Component actions")
    assert "[role^=menuitem]" in panel
    assert "[role=menuitem]" not in panel


def test_panel_without_a_role_drops_the_menu_semantics(rendered: str) -> None:
    panel = _opening(rendered, PANEL, "SBOM uploaded")
    assert "role=" not in panel
    assert "aria-orientation" not in panel
    assert "@keydown" not in panel


def test_panel_forwards_the_alpine_positioning_hooks(rendered: str) -> None:
    panel = _opening(rendered, PANEL, "Download")
    assert 'x-ref="menu"' in panel
    assert 'x-show="open"' in panel
    assert "x-cloak" in panel
    assert ':style="style"' in panel
    assert '@click.outside="close()"' in panel


def test_panel_width_comes_from_the_caller_class(rendered: str) -> None:
    assert _classes(rendered, PANEL, "Component actions").endswith("w-64")
    assert _classes(rendered, PANEL, "SBOM uploaded").endswith("w-72")


# ── Items, headers and dividers ──────────────────────────────────────────────


def test_item_carries_the_shared_row(rendered: str) -> None:
    item = _classes(rendered, ITEM, "Edit")
    for bit in (
        "flex items-center gap-3 w-full px-2.5 py-2 rounded-lg text-sm font-semibold",
        "text-left no-underline cursor-pointer",
        "transition-all duration-150",
        "focus-visible:outline-none",
    ):
        assert bit in item


def test_default_item_is_the_neutral_recipe(rendered: str) -> None:
    item = _classes(rendered, ITEM, "Edit")
    assert "text-text hover:bg-[color-mix(in_oklab,var(--color-primary)_8%,transparent)] hover:text-primary" in item
    assert "focus-visible:text-primary" in item
    assert "text-danger" not in item


def test_danger_item_replaces_the_colour_whole(rendered: str) -> None:
    item = _classes(rendered, ITEM, "Delete component")
    assert "text-danger hover:bg-[color-mix(in_oklab,var(--color-danger)_10%,transparent)] hover:text-danger" in item
    assert "focus-visible:text-danger" in item
    assert "text-primary" not in item
    assert "text-text " not in item


def test_every_item_is_a_menu_item(rendered: str) -> None:
    assert 'role="menuitem"' in _item_opening(rendered, "Edit")
    assert 'role="menuitem"' in _item_opening(rendered, "Leave workspace")


def test_item_icon_sits_in_a_gutter_and_follows_the_row_colour(rendered: str) -> None:
    icon = _classes(rendered, "fas fa-pen", "aria-hidden")
    assert icon == (
        "fas fa-pen shrink-0 w-4 text-center text-text-muted group-hover:text-inherit group-focus-visible:text-inherit"
    )
    assert _classes(rendered, ITEM, "Edit").startswith("group ")


def test_item_without_an_href_is_a_button(rendered: str) -> None:
    item = _item_opening(rendered, "Edit")
    assert item.startswith("<button")
    assert 'type="button"' in item
    assert "href=" not in item


def test_item_with_an_href_is_an_anchor(rendered: str) -> None:
    item = _item_opening(rendered, "Duplicate")
    assert item.startswith("<a ")
    assert 'href="/components/1/duplicate"' in item
    assert "no-underline" in item
    assert 'hx-boost="false"' in item


def test_disabled_button_item_uses_the_real_attribute(rendered: str) -> None:
    item = _item_opening(rendered, "Locked")
    assert "disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none" in item
    assert re.search(r"\sdisabled\s", item), "the disabled attribute is missing from the button"


def test_disabled_anchor_item_is_removed_from_the_tab_order(rendered: str) -> None:
    item = _item_opening(rendered, "Archive")
    assert 'tabindex="-1" aria-disabled="true"' in item
    assert "aria-disabled:opacity-50 aria-disabled:cursor-not-allowed aria-disabled:pointer-events-none" in item


def test_item_attrs_pass_through_variant_and_base_untouched(rendered: str) -> None:
    item = _item_opening(rendered, "Delete component")
    assert 'hx-delete="/components/1"' in item
    assert 'hx-confirm="Really?"' in item
    assert '@click="edit()"' in _item_opening(rendered, "Edit")


def test_item_slot_carries_nested_markup(rendered: str) -> None:
    assert "<span>Leave workspace</span>" in rendered


def test_header_and_divider_recipes(rendered: str) -> None:
    header = _classes(rendered, "pt-1.5", "Component actions")
    assert header == "pt-1.5 px-2.5 pb-1 text-[0.625rem] font-bold uppercase tracking-[0.08em] text-text-muted"
    assert 'class="h-px my-1.5 bg-[color-mix(in_oklab,var(--color-border)_50%,transparent)]"' in rendered


# ── Icon chips ───────────────────────────────────────────────────────────────


def test_icon_chip_shares_the_centring_shell(rendered: str) -> None:
    assert _classes(rendered, ICON_CHIP, "fa-credit-card").startswith(ICON_CHIP)


@pytest.mark.parametrize(
    ("marker", "segment"),
    [
        ("fa-credit-card", "w-10 h-10 rounded-lg"),
        ("fa-key", "w-8 h-8 text-sm rounded-md"),
        ("fa-cube", "w-12 h-12 text-lg rounded-[0.625rem]"),
        ("fa-box", "w-14 h-14 text-xl rounded-xl"),
    ],
)
def test_icon_chip_size_segments(rendered: str, marker: str, segment: str) -> None:
    assert segment in _classes(rendered, ICON_CHIP, marker)


@pytest.mark.parametrize(
    ("marker", "token", "foreground"),
    [
        ("fa-plus", "text-muted", "text-text-muted"),
        ("fa-circle-info", "info", "text-info"),
        ("fa-check", "success", "text-success"),
        ("fa-clock", "warning", "text-warning"),
        ("fa-triangle-exclamation", "danger", "text-danger"),
    ],
)
def test_icon_chip_accent_segments(rendered: str, marker: str, token: str, foreground: str) -> None:
    chip = _classes(rendered, ICON_CHIP, marker)
    assert f"bg-[color-mix(in_oklab,var(--color-{token})_12%,transparent)] {foreground}" in chip
    assert "--chip-accent" not in chip


def test_icon_chip_without_an_accent_stays_parameterized(rendered: str) -> None:
    chip = _classes(rendered, ICON_CHIP, "fa-credit-card")
    assert "bg-[color-mix(in_oklab,var(--chip-accent,var(--color-primary))_12%,transparent)]" in chip
    assert "text-[color:var(--chip-accent,var(--color-primary))]" in chip


def test_icon_chip_circle_replaces_the_size_radius(rendered: str) -> None:
    medallion = _classes(rendered, ICON_CHIP, "fa-triangle-exclamation")
    assert "w-14 h-14 text-xl rounded-full" in medallion
    assert "rounded-xl" not in medallion
    small_circle = _classes(rendered, ICON_CHIP, "fa-inbox")
    assert "w-8 h-8 text-sm rounded-full" in small_circle
    assert "rounded-md" not in small_circle


def test_icon_chip_forwards_attrs_and_caller_class(rendered: str) -> None:
    assert _classes(rendered, ICON_CHIP, "fa-triangle-exclamation").endswith("mx-auto")
    assert 'title="Danger medallion"' in _opening(rendered, ICON_CHIP, "fa-triangle-exclamation")
    assert 'style="--chip-accent: var(--color-accent-pink)"' in _opening(rendered, ICON_CHIP, "fa-inbox")


# ── Metric chips ─────────────────────────────────────────────────────────────


def test_metric_chip_shares_the_pill_shell(rendered: str) -> None:
    chip = _classes(rendered, METRIC_CHIP, "Components")
    assert chip.startswith(
        "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-solid text-sm leading-[1.5]"
    )


def test_metric_chip_default_is_the_bordered_surface(rendered: str) -> None:
    chip = _classes(rendered, METRIC_CHIP, "Components")
    assert "bg-surface border-border text-text" in chip
    assert "color-mix" not in chip


@pytest.mark.parametrize(
    ("accent", "marker"),
    [("info", "SBOMs"), ("success", "Passed"), ("warning", "Scanned"), ("danger", "Critical")],
)
def test_metric_chip_accent_segments_tint_fill_border_and_text(rendered: str, accent: str, marker: str) -> None:
    chip = _classes(rendered, METRIC_CHIP, marker)
    assert f"bg-[color-mix(in_oklab,var(--color-{accent})_10%,transparent)]" in chip
    assert f"border-[color-mix(in_oklab,var(--color-{accent})_30%,transparent)]" in chip
    assert f"text-[color:color-mix(in_oklab,var(--color-{accent})_60%,var(--color-text))]" in chip
    assert "bg-surface" not in chip


def test_metric_chip_parts_keep_the_label_muted_and_the_value_tabular(rendered: str) -> None:
    assert _classes(rendered, "text-text-muted", "Components") == "text-text-muted"
    assert _classes(rendered, "font-semibold tabular-nums", "12</span>") == "font-semibold tabular-nums"
    # The label stays muted under an accent, so only the value takes the chip's colour.
    assert _classes(rendered, "text-text-muted", "Critical") == "text-text-muted"


def test_metric_chip_slot_keeps_the_callers_order(rendered: str) -> None:
    # "Scanned 3h ago" reads label first; the component must not impose an order.
    assert rendered.index("Scanned") < rendered.index("3h ago")


def test_metric_chip_forwards_attrs_and_caller_class(rendered: str) -> None:
    assert _classes(rendered, METRIC_CHIP, "SBOMs").endswith("ml-2")
    assert "@click=\"filter('sboms')\"" in _opening(rendered, METRIC_CHIP, "SBOMs")


# ── Assessment pills ─────────────────────────────────────────────────────────


def test_assessment_pill_shares_one_shell(rendered: str) -> None:
    pill = _classes(rendered, ASSESSMENT, "NTIA")
    assert pill.startswith(
        "inline-flex items-center justify-center gap-1 px-2 py-1 text-[0.6875rem] leading-[1.5] "
        "font-semibold rounded-md whitespace-nowrap border border-solid"
    )
    assert "[&_i]:text-[0.625rem]" in pill


def test_assessment_pill_without_a_status_is_the_quiet_tint(rendered: str) -> None:
    pill = _opening(rendered, ASSESSMENT, "+2")
    assert 'data-status=""' in pill
    classes = _classes(rendered, ASSESSMENT, "+2")
    assert "text-text-muted bg-[color-mix(in_oklab,var(--color-border)_20%,transparent)]" in classes
    assert "border-[color-mix(in_oklab,var(--color-border)_40%,transparent)]" in classes


@pytest.mark.parametrize(
    ("marker", "token"),
    [("NTIA", "success"), ("PQC", "info"), ("SPDX", "danger")],
)
def test_assessment_pill_token_recipes_are_keyed_by_the_attribute(rendered: str, marker: str, token: str) -> None:
    pill = _classes(rendered, ASSESSMENT, marker)
    status = {"success": "pass", "info": "pending", "danger": "error"}[token]
    assert f"data-[status={status}]:bg-[color-mix(in_oklab,var(--color-{token})_10%,transparent)]" in pill
    assert f"data-[status={status}]:border-[color-mix(in_oklab,var(--color-{token})_25%,transparent)]" in pill
    assert f"data-[status={status}]:hover:bg-[color-mix(in_oklab,var(--color-{token})_15%,transparent)]" in pill


def test_assessment_pill_keeps_the_literal_ambers_and_reds(rendered: str) -> None:
    """fail and summary-fail were raw values in the stylesheet, not the tokens."""
    pill = _classes(rendered, ASSESSMENT, "CRA")
    assert "data-[status=fail]:text-[#b45309]" in pill
    assert "data-[status=fail]:bg-[rgb(245_158_11/0.12)]" in pill
    assert "data-[status=summary-fail]:text-[#dc2626]" in pill
    assert "data-[status=summary-fail]:bg-[rgb(239_68_68/0.1)]" in pill


def test_assessment_pill_carries_every_recipe_whatever_the_status(rendered: str) -> None:
    """The recipes are the component's, so a bound status has them all to pick from."""
    for marker in ("NTIA", "+2", "Bound"):
        pill = _classes(rendered, ASSESSMENT, marker)
        for status in ("pass", "fail", "pending", "error", "summary-fail"):
            assert f"data-[status={status}]:" in pill


def test_assessment_pill_every_status_brings_its_own_hover(rendered: str) -> None:
    """Without one the fallback's hover would outrank the status at hover time."""
    pill = _classes(rendered, ASSESSMENT, "NTIA")
    for status in ("pass", "fail", "pending", "error", "summary-fail"):
        assert f"data-[status={status}]:hover:bg-" in pill


def test_assessment_pill_binds_state_not_classes(rendered: str) -> None:
    pill = _opening(rendered, ASSESSMENT, "Bound")
    assert ':data-status="plugin.status"' in pill
    assert 'x-text="plugin.display_name"' in pill
    assert ":class=" not in pill


def test_assessment_pill_forwards_attrs_and_caller_class(rendered: str) -> None:
    assert _classes(rendered, ASSESSMENT, "+2").endswith("ml-1")
    assert 'title="2 more assessments"' in _opening(rendered, ASSESSMENT, "+2")
