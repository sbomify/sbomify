"""Render contract for the cotton badges and tags component sets.

The probe template exercises every component in components/badges and
components/tags; these tests pin the shells and the utility recipes each variant
emits, so pages can rely on the components without ever writing a class
themselves.
"""

import pytest
from django.template.loader import render_to_string


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string("core/cotton_probes/badges_tags.html.j2")


def _span_holding(rendered: str, marker: str) -> str:
    """The one span whose own markup, up to its first close, holds the marker."""
    chunks = [part.split("</span>")[0] for part in rendered.split("<span")]
    holders = [chunk for chunk in chunks if marker in chunk]
    assert holders, f"no span holds {marker!r}"
    return holders[0]


def _badge(rendered: str, label: str) -> str:
    return _span_holding(rendered, label)


@pytest.mark.parametrize(
    ("label", "recipe_bit"),
    [
        ("Bare", "text-text-muted bg-[color-mix(in_oklab,var(--color-border)_12%,transparent)]"),
        ("Primary", "text-primary bg-[color-mix(in_oklab,var(--color-primary)_12%,transparent)]"),
        ("Secondary", "text-text-muted bg-[color-mix(in_oklab,var(--color-border)_30%,transparent)]"),
        ("Success", "text-success bg-[color-mix(in_oklab,var(--color-success)_12%,transparent)]"),
        ("Warning", "text-warning bg-[color-mix(in_oklab,var(--color-warning)_12%,transparent)]"),
        ("Danger", "text-danger bg-[color-mix(in_oklab,var(--color-danger)_12%,transparent)]"),
        ("Info", "text-info bg-[color-mix(in_oklab,var(--color-info)_12%,transparent)]"),
        ("Violet", "text-accent bg-[color-mix(in_oklab,var(--color-accent)_12%,transparent)]"),
        ("Accent", "bg-[linear-gradient(135deg,var(--color-primary-dark)_0%,#CC58BB_100%)]"),
        ("KEV", "text-white bg-danger"),
    ],
)
def test_badge_variants_carry_their_recipe(rendered: str, label: str, recipe_bit: str) -> None:
    assert recipe_bit in _badge(rendered, label)


@pytest.mark.parametrize(
    ("label", "recipe_bit"),
    [
        ("Bare", "border-[color-mix(in_oklab,var(--color-border)_20%,transparent)]"),
        ("Primary", "border-[color-mix(in_oklab,var(--color-primary)_20%,transparent)]"),
        ("Secondary", "border-[color-mix(in_oklab,var(--color-border)_50%,transparent)]"),
        ("Accent", "border-[color-mix(in_oklab,var(--color-border)_20%,transparent)]"),
        ("KEV", "border-[color-mix(in_oklab,var(--color-danger)_20%,transparent)]"),
    ],
)
def test_badge_variants_carry_their_hairline(rendered: str, label: str, recipe_bit: str) -> None:
    badge = _badge(rendered, label)
    assert "border border-solid" in badge
    assert recipe_bit in badge


def test_shared_badge_shell_structure(rendered: str) -> None:
    primary = _badge(rendered, "Primary")
    for bit in ("inline-flex", "items-center", "font-semibold", "transition-all duration-150"):
        assert bit in primary


def test_default_badge_shape_segment(rendered: str) -> None:
    assert "px-3 py-1 text-xs leading-[1.5] tracking-[0.01em]" in _badge(rendered, "Primary")
    assert "rounded-full" in _badge(rendered, "Primary")


def test_small_badge_segment_replaces_the_default(rendered: str) -> None:
    compact = _badge(rendered, "Compact")
    assert "px-1.5 py-0.5 text-[0.625rem] leading-[1.5] tracking-[0.01em]" in compact
    assert "px-3 py-1 " not in compact
    assert "text-xs" not in compact


def test_pill_keeps_the_default_shell_round_without_stacking_radii(rendered: str) -> None:
    pilled = _badge(rendered, "Pilled")
    assert pilled.count("rounded-full") == 1
    assert "rounded " not in pilled


def test_badge_attrs_pass_through_variant_and_base_untouched(rendered: str) -> None:
    nested = _badge(rendered, '<i class="fas fa-star"')
    assert 'hx-get="/probe"' in nested
    assert '@click="pick()"' in nested
    assert 'aria-label="Probe badge"' in nested
    assert "ml-2" in nested


def test_badge_slot_carries_nested_markup(rendered: str) -> None:
    assert '<i class="fas fa-star" aria-hidden="true"></i> <span>Nested</span>' in rendered


@pytest.mark.parametrize(
    ("label", "token"),
    [
        ("Critical", "var(--color-severity-critical)"),
        ("High", "var(--color-severity-high)"),
        ("Medium", "var(--color-severity-medium)"),
        ("Low", "var(--color-severity-low)"),
        ("Unknown", "var(--color-text-muted)"),
        ("Off scale", "var(--color-text-muted)"),
    ],
)
def test_severity_level_prop_picks_the_band_accent(rendered: str, label: str, token: str) -> None:
    badge = _badge(rendered, label)
    assert f"text-[color-mix(in_oklab,{token}_70%,var(--color-text))]" in badge
    assert f"bg-[color-mix(in_oklab,{token}_12%,transparent)]" in badge
    assert f"border-[color-mix(in_oklab,{token}_20%,transparent)]" in badge


def test_severity_shape_segment_replaces_the_badge_shape(rendered: str) -> None:
    critical = _badge(rendered, "Critical")
    assert "px-2 py-1 text-xs leading-[1.5] uppercase tracking-[0.04em]" in critical
    assert "rounded" in critical
    assert "rounded-full" not in critical
    assert "px-3" not in critical
    assert "tracking-[0.01em]" not in critical


def test_severity_shares_the_badge_shell(rendered: str) -> None:
    assert "inline-flex items-center font-semibold" in _badge(rendered, "Critical")


def test_pill_rounds_the_severity_shape(rendered: str) -> None:
    rounded = _badge(rendered, "Rounded high")
    assert "rounded-full" in rounded
    assert "uppercase" in rounded


@pytest.mark.parametrize(
    ("label", "recipe_bit"),
    [
        ("CycloneDX", "text-[#0d9488] bg-[rgb(20_184_166/0.1)]"),
        ("SPDX", "text-[#7c3aed] bg-[rgb(139_92_246/0.1)]"),
    ],
)
def test_format_prop_picks_the_format_colour(rendered: str, label: str, recipe_bit: str) -> None:
    badge = _badge(rendered, label)
    assert recipe_bit in badge
    assert "text-[0.6875rem] font-bold tracking-[0.03em] rounded-md whitespace-nowrap" in badge


def test_format_hover_tint_travels_with_the_variant(rendered: str) -> None:
    assert "hover:bg-[rgb(20_184_166/0.15)]" in _badge(rendered, "CycloneDX")
    assert "hover:bg-[rgb(139_92_246/0.15)]" in _badge(rendered, "SPDX")


def test_unknown_format_keeps_the_shape_without_a_tint(rendered: str) -> None:
    swid = _badge(rendered, "SWID")
    assert "inline-flex items-center px-2.5 py-1" in swid
    assert "border-[rgb" not in swid


def test_format_badge_is_not_the_badge_shell(rendered: str) -> None:
    assert "font-semibold" not in _badge(rendered, "CycloneDX")


@pytest.mark.parametrize(
    ("label", "recipe_bit"),
    [
        ("Neutral", "text-text bg-[color-mix(in_oklab,var(--color-border)_30%,transparent)]"),
        ("Tag primary", "text-primary bg-[color-mix(in_oklab,var(--color-primary)_12%,transparent)]"),
        ("Tag success", "text-success bg-[color-mix(in_oklab,var(--color-success)_12%,transparent)]"),
        ("Tag warning", "text-warning bg-[color-mix(in_oklab,var(--color-warning)_12%,transparent)]"),
        ("Tag danger", "text-danger bg-[color-mix(in_oklab,var(--color-danger)_12%,transparent)]"),
    ],
)
def test_tag_variants_carry_their_recipe(rendered: str, label: str, recipe_bit: str) -> None:
    assert recipe_bit in _span_holding(rendered, label)


def test_shared_tag_shell_structure(rendered: str) -> None:
    neutral = _span_holding(rendered, "Neutral")
    assert "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs leading-[1.5] font-medium rounded-md" in neutral
    assert "transition-all duration-150" in neutral


def test_tag_attrs_and_class_pass_through(rendered: str) -> None:
    python = _span_holding(rendered, "fab fa-python")
    assert 'title="Probe tag"' in python
    assert '@click="edit()"' in python
    assert "font-mono" in python


def test_tag_slot_carries_nested_markup(rendered: str) -> None:
    assert '<i class="fab fa-python" aria-hidden="true"></i> <span>Python</span>' in rendered


def test_removable_renders_the_close_button_with_an_accessible_name(rendered: str) -> None:
    close = _span_holding(rendered, "MIT")
    assert 'type="button"' in close
    assert 'aria-label="Remove MIT"' in close
    assert 'class="fas fa-times"' in close
    assert "w-[1.125rem] h-[1.125rem] rounded-full ml-0.5 -mr-1 opacity-60" in close
    assert "hover:bg-[color-mix(in_oklab,var(--color-danger)_20%,transparent)]" in close


def test_close_button_is_absent_without_removable(rendered: str) -> None:
    assert "<button" not in _span_holding(rendered, "Neutral")


def test_remove_click_carries_the_alpine_handler(rendered: str) -> None:
    close = _span_holding(rendered, "Ada Lovelace")
    assert '@click.stop="removeContact(index)"' in close
    assert 'aria-label="Remove Ada Lovelace"' in close


def test_removable_travels_through_a_variant_file(rendered: str) -> None:
    ada = _span_holding(rendered, "Ada Lovelace")
    assert "text-primary bg-[color-mix(in_oklab,var(--color-primary)_12%,transparent)]" in ada
    assert "<button" in ada


def _probe(rendered: str, name: str) -> str:
    """The element carrying data-probe=name, from its tag open to the next one."""
    marker = f'data-probe="{name}"'
    assert marker in rendered, f"probe {name} missing"
    start = rendered.rindex("<", 0, rendered.index(marker))
    return rendered[start : rendered.index(">", rendered.index(marker)) + 1]


def test_dynamic_badge_keeps_every_recipe_and_binds_only_the_variant(rendered: str) -> None:
    danger = _probe(rendered, "dyn-danger")
    assert 'data-variant="danger"' in danger
    # The recipes stay in the component, keyed by the attribute.
    assert "data-[variant=danger]:text-danger" in danger
    assert "data-[variant=success]:text-success" in danger
    # And the neutral tint is the resting state, so an unknown variant degrades quietly.
    assert "text-text-muted" in danger


def test_dynamic_badge_defaults_to_the_neutral_variant(rendered: str) -> None:
    assert 'data-variant="secondary"' in _probe(rendered, "dyn-default")


def test_dynamic_badge_size_segment_matches_the_named_badges(rendered: str) -> None:
    assert "px-1.5 py-0.5 text-[0.625rem] leading-[1.5]" in _probe(rendered, "dyn-sm")


def test_neutral_chip_recipe(rendered: str) -> None:
    chip = _probe(rendered, "chip-neutral")
    assert "px-2 py-1 text-xs font-semibold leading-tight rounded-lg" in chip
    assert "text-text-muted" in chip


def test_tag_renders_an_anchor_with_href_and_no_underline(rendered: str) -> None:
    tag = _probe(rendered, "tag-link")
    assert tag.startswith("<a ")
    assert 'href="/components/x"' in tag
    assert "no-underline" in tag
