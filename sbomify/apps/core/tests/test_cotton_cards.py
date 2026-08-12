"""Render contract for the cotton cards component set.

The probe template exercises every component in components/cards; these tests
pin the surface recipes, the header, body and footer bands, and the Alpine
wiring of the collapsible, so pages can rely on the components without ever
writing a class themselves.
"""

import pytest
from django.template.loader import render_to_string

CARD_SHELL = "rounded-xl transition-all duration-300"
DEFAULT_SURFACE = "bg-surface border border-solid border-border shadow-[var(--shadow-card)]"
HAIRLINE = "border-[color-mix(in_oklab,var(--color-border)_50%,transparent)]"


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string("core/cotton_probes/cards.html.j2")


def _card_holding(rendered: str, marker: str) -> str:
    """The markup of the card that contains `marker`.

    Cards are plain divs, so slice from the last shell opening before the
    marker to the marker itself: everything the card wraps is in between.
    """
    at = rendered.index(marker)
    start = rendered.rindex(CARD_SHELL, 0, at)
    return rendered[start : at + len(marker)]


def _region(rendered: str, marker: str, depth: int = 0) -> str:
    """From the `depth`-th enclosing <div> before `marker`, up to the marker."""
    at = rendered.index(marker)
    start = at
    for _ in range(depth + 1):
        start = rendered.rindex("<div", 0, start)
    return rendered[start : at + len(marker)]


def _open_tag(rendered: str, marker: str, depth: int = 0) -> str:
    """The opening <div> tag `depth` levels out from `marker`, attributes and all."""
    region = _region(rendered, marker, depth)
    return region[: region.index(">") + 1]


def _button_holding(rendered: str, marker: str) -> str:
    chunks = [part for part in rendered.split("<button") if marker in part]
    assert chunks, f"no button holds {marker!r}"
    return chunks[0]


def test_default_surface_is_the_still_card(rendered: str) -> None:
    card = _card_holding(rendered, "Body copy")
    assert DEFAULT_SURFACE in card
    assert "hover:" not in card.split(">")[0]
    assert "animate-" not in card


def test_header_band_carries_the_rule_and_the_wash(rendered: str) -> None:
    header = _open_tag(rendered, "Plain surface", depth=1)
    assert "px-6 py-5 border-b border-solid" in header
    assert HAIRLINE in header
    assert (
        "bg-[linear-gradient(to_bottom,color-mix(in_oklab,var(--color-surface-elevated)_50%,transparent),transparent)]"
        in header
    )


def test_title_and_subtitle_render_in_the_standard_header(rendered: str) -> None:
    header = _card_holding(rendered, "Body copy")
    assert 'class="text-lg font-semibold m-0 text-text"' in header
    assert "Plain surface" in header
    assert '<p class="text-sm text-text-muted mt-0.5">Header and body</p>' in header


def test_icon_prop_renders_a_hidden_icon(rendered: str) -> None:
    assert 'class="fas fa-cube text-text-muted mr-2"' in rendered
    assert 'aria-hidden="true"' in _card_holding(rendered, "Iconned")


def test_card_without_a_title_has_no_header_band(rendered: str) -> None:
    card = _card_holding(rendered, "Bodyonly")
    assert "border-b border-solid" not in card


def test_body_band_is_the_padded_region(rendered: str) -> None:
    assert 'class="p-6"' in _open_tag(rendered, "Standalone body")


def test_flush_card_drops_the_padded_body(rendered: str) -> None:
    """Content that owns its padding sits straight on the card surface."""
    card = _card_holding(rendered, "Flush body")
    assert '<div class="p-6"' not in card
    assert "<div>Flush body" in card
    # The header band is unaffected: only the body is dropped.
    assert "border-b border-solid" in card


def test_footer_slot_renders_the_footer_band(rendered: str) -> None:
    footer = _open_tag(rendered, "Footer actions")
    assert "px-6 py-4 border-t border-solid" in footer
    assert "bg-[color-mix(in_oklab,var(--color-background)_30%,transparent)]" in footer


def test_card_class_stays_on_the_card_and_off_its_bands(rendered: str) -> None:
    card = _card_holding(rendered, "Footed body")
    assert f"{DEFAULT_SURFACE} mb-8" in card
    # One class only: the header and body must not inherit the card's layout.
    assert card.count("mb-8") == 1


def test_attrs_pass_through_to_the_card(rendered: str) -> None:
    card = _card_holding(rendered, "Footed body")
    assert 'hx-get="/probe"' in card
    assert '@click.stop="fire()"' in card


def test_header_slot_replaces_the_standard_header(rendered: str) -> None:
    card = _card_holding(rendered, "Slot precedence body")
    assert "Slot wins" in card
    assert "Ignored when a header slot is given" not in card


def test_standalone_header_part_takes_layout_class(rendered: str) -> None:
    header = _open_tag(rendered, "Hand built header")
    assert "px-6 py-5" in header
    assert "flex items-center justify-between" in header


def test_dashboard_clips_the_surface(rendered: str) -> None:
    card = _card_holding(rendered, "Dashboard body")
    assert f"{DEFAULT_SURFACE} relative overflow-hidden" in card
    assert 'data-probe="dashboard"' in card
    assert "col-span-2" in card


def test_variant_forwards_a_named_slot_to_the_card(rendered: str) -> None:
    footer = _open_tag(rendered, "Dashboard footer")
    assert "px-6 py-4 border-t border-solid" in footer


@pytest.mark.parametrize(
    "recipe_bit",
    [
        "border-2 border-solid border-[color-mix(in_oklab,var(--color-danger)_50%,transparent)]",
        "bg-[color-mix(in_oklab,var(--color-danger)_4%,transparent)]",
        "hover:border-[color-mix(in_oklab,var(--color-danger)_70%,transparent)]",
        "hover:bg-[color-mix(in_oklab,var(--color-danger)_6%,transparent)]",
        "hover:shadow-[0_4px_12px_-1px_rgb(239_68_68/0.25),0_2px_6px_-2px_rgb(239_68_68/0.15)]",
    ],
)
def test_dangerzone_surface_recipe(rendered: str, recipe_bit: str) -> None:
    assert recipe_bit in _card_holding(rendered, "Danger body")


def test_dangerzone_surface_never_stacks_with_the_default(rendered: str) -> None:
    shell = _card_holding(rendered, "Danger body").split(">")[0]
    assert "bg-surface" not in shell
    assert "border-border" not in shell


def test_dangerzone_repaints_its_header_and_body(rendered: str) -> None:
    header = _open_tag(rendered, "Danger zone", depth=1)
    assert "flex items-center gap-3" in header
    assert "border-[color-mix(in_oklab,var(--color-danger)_30%,transparent)]" in header
    assert (
        "bg-[linear-gradient(135deg,color-mix(in_oklab,var(--color-danger)_8%,transparent)_0%,"
        "color-mix(in_oklab,var(--color-danger)_12%,transparent)_100%)]" in header
    )
    assert "focus-visible:shadow-[inset_0_0_0_2px_color-mix(in_oklab,var(--color-danger)_50%,transparent)]" in header
    assert HAIRLINE not in header
    body = _open_tag(rendered, "Danger body")
    assert "p-6 bg-[color-mix(in_oklab,var(--color-danger)_2%,transparent)]" in body


def test_dangerzone_header_ink_is_danger(rendered: str) -> None:
    header = _card_holding(rendered, "Danger body")
    assert 'class="fas fa-exclamation-triangle text-danger"' in header
    assert 'class="text-lg font-semibold m-0 text-danger"' in header
    assert "text-text-muted mr-2" not in header


def test_dangerzone_icon_prop_overrides_the_warning_default(rendered: str) -> None:
    header = _card_holding(rendered, "Skulled")
    assert 'class="fas fa-skull text-danger"' in header


def test_dangerzone_header_part_paints_the_same_band_as_the_title_header(rendered: str) -> None:
    trigger = _open_tag(rendered, "Danger zone trigger")
    title_band = _open_tag(rendered, "Danger zone", depth=1)
    for bit in (
        "flex items-center gap-3",
        "border-[color-mix(in_oklab,var(--color-danger)_30%,transparent)]",
        "bg-[linear-gradient(135deg,color-mix(in_oklab,var(--color-danger)_8%,transparent)_0%,"
        "color-mix(in_oklab,var(--color-danger)_12%,transparent)_100%)]",
        "focus-visible:shadow-[inset_0_0_0_2px_color-mix(in_oklab,var(--color-danger)_50%,transparent)]",
    ):
        assert bit in trigger
        assert bit in title_band


def test_dangerzone_header_part_carries_the_control_attributes(rendered: str) -> None:
    trigger = _open_tag(rendered, "Danger zone trigger")
    assert 'role="button"' in trigger
    assert 'tabindex="0"' in trigger
    assert ':aria-expanded="isExpanded"' in trigger
    assert '@click="toggle()"' in trigger
    assert "cursor-pointer select-none" in trigger


def test_dangerzone_body_part_takes_the_collapse_on_the_padded_element(rendered: str) -> None:
    body = _open_tag(rendered, "Collapsible danger body")
    assert "p-6 bg-[color-mix(in_oklab,var(--color-danger)_2%,transparent)]" in body
    assert 'x-show="isExpanded"' in body
    assert "x-collapse" in body


def test_flush_dangerzone_emits_no_padded_body_of_its_own(rendered: str) -> None:
    card = _card_holding(rendered, "Collapsible danger body")
    assert card.count("p-6 bg-[color-mix(in_oklab,var(--color-danger)_2%,transparent)]") == 1


def test_inset_is_sunken_not_raised(rendered: str) -> None:
    inset = _open_tag(rendered, "Outer inset")
    assert "rounded-xl border border-solid border-border p-4" in inset
    assert "bg-[color-mix(in_oklab,var(--color-background)_50%,transparent)]" in inset
    assert "shadow-" not in inset


def test_nested_inset_goes_solid_by_the_descendant_marker(rendered: str) -> None:
    inner = _open_tag(rendered, "Inner inset")
    assert "data-inset" in inner
    assert "[[data-inset]_&]:bg-background" in inner
    assert "mt-3" in inner


def test_collapsible_shell_defaults_to_the_neutral_border(rendered: str) -> None:
    shell = _open_tag(rendered, "Product links")
    assert "bg-surface rounded-xl overflow-hidden border border-solid" in shell
    assert "border-border" in shell


@pytest.mark.parametrize(
    ("marker", "token"),
    [
        ("Clean run", "success"),
        ("Warning shell", "warning"),
        ("Danger shell", "danger"),
    ],
)
def test_collapsible_level_repaints_only_the_border(rendered: str, marker: str, token: str) -> None:
    shell = _open_tag(rendered, marker)
    assert f"border-[color-mix(in_oklab,var(--color-{token})_30%,transparent)]" in shell
    assert "border-border" not in shell


def test_collapsible_shell_takes_attrs(rendered: str) -> None:
    assert 'id="probe-warning"' in _open_tag(rendered, "Warning shell")


def test_collapsible_trigger_is_a_real_button_with_state(rendered: str) -> None:
    trigger = _button_holding(rendered, "Product links")
    assert 'type="button"' in trigger
    assert "flex w-full items-center justify-between px-6 py-5 text-left" in trigger
    assert "hover:bg-[color-mix(in_oklab,var(--color-primary)_3%,transparent)]" in trigger
    assert "focus-visible:shadow-[inset_0_0_0_2px_color-mix(in_oklab,var(--color-primary)_50%,transparent)]" in trigger
    # Django escapes the quotes in the expression; the browser hands Alpine the
    # decoded attribute, so the binding still reads `open === 'links'`.
    assert ':aria-expanded="open === &#x27;links&#x27;"' in trigger
    assert "@click=\"open = open === 'links' ? '' : 'links'\"" in trigger


def test_collapsible_trigger_turns_the_chevron_over(rendered: str) -> None:
    trigger = _button_holding(rendered, "Clean run")
    assert '<i class="fas fa-chevron-down text-text-muted transition-transform duration-300"' in trigger
    assert ":class=\"expanded ? 'rotate-180' : ''\"" in trigger
    assert '<span class="flex items-center gap-3 font-semibold text-text">Clean run</span>' in trigger


def test_bare_trigger_puts_the_row_straight_into_the_button(rendered: str) -> None:
    trigger = _button_holding(rendered, "Bare row")
    assert '<span class="flex items-center gap-3 font-semibold text-text">' not in trigger
    assert '<div class="flex items-center gap-3 flex-grow min-w-0">' in trigger
    # The chevron and the state binding are the trigger's own either way.
    assert '<i class="fas fa-chevron-down text-text-muted transition-transform duration-300"' in trigger
    assert ':aria-expanded="expanded"' in trigger


def test_collapsible_body_collapses_the_clipped_wrapper(rendered: str) -> None:
    wrapper = _open_tag(rendered, "Success panel", depth=1)
    assert 'class="overflow-hidden"' in wrapper
    assert 'x-show="expanded" x-collapse' in wrapper
    padded = _open_tag(rendered, "Success panel")
    assert "px-6 pt-5 pb-6 border-t border-solid" in padded
    assert HAIRLINE in padded


def test_collapsible_without_state_stays_open(rendered: str) -> None:
    assert "x-show" not in _open_tag(rendered, "Danger shell")
