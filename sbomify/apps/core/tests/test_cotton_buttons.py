"""Render contract for the cotton buttons component set.

The probe template exercises every component in components/buttons; these
tests pin the shell structure and the utility recipes each variant emits, so
pages can rely on the components without ever writing a class themselves.
"""

import pytest
from django.template.loader import render_to_string


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string("core/cotton_probes/buttons.html.j2")


def _button_holding(rendered: str, marker: str) -> str:
    chunks = [part for part in rendered.split("<button") if marker in part]
    assert chunks, f"no button holds {marker!r}"
    return chunks[0]


@pytest.mark.parametrize(
    ("marker", "recipe_bit"),
    [
        ("Save", "var(--color-primary)_0%,var(--color-primary-dark)_100%"),
        ("Confirm", "var(--color-success)_0%,var(--color-success-dark)_100%"),
        ("Care", "var(--color-warning)_0%,var(--color-warning-dark)_100%"),
        ("Delete", "var(--color-danger)_0%,var(--color-danger-dark)_100%"),
        ("Cancel", "bg-surface"),
        ("Quiet", "hover:bg-surface"),
        ("Revoke all", "hover:bg-[color-mix(in_oklab,var(--color-danger)_10%,transparent)] hover:text-danger"),
        ("Shiny", "var(--color-accent-pink)_50%"),
    ],
)
def test_filled_variants_carry_their_recipe(rendered: str, marker: str, recipe_bit: str) -> None:
    assert recipe_bit in _button_holding(rendered, marker)


@pytest.mark.parametrize(
    ("marker", "recipe_bit"),
    [
        ("Neutral", "border-[1.5px] border-solid border-border"),
        ("Choose", "border-[1.5px] border-solid border-primary"),
        ("Hold", "border-[1.5px] border-solid border-warning"),
        ("Remove", "border-[1.5px] border-solid border-danger"),
        ("Approve", "border-[1.5px] border-solid border-success"),
    ],
)
def test_outline_variants_carry_their_border(rendered: str, marker: str, recipe_bit: str) -> None:
    assert recipe_bit in _button_holding(rendered, marker)


def test_outline_success_fills_with_the_success_gradient_on_hover(rendered: str) -> None:
    """The green outline the controls catalogue used to reach for with --btn-accent."""
    approve = _button_holding(rendered, "Approve")
    assert "hover:bg-[linear-gradient(135deg,var(--color-success)_0%,var(--color-success-dark)_100%)]" in approve
    assert "text-success" in approve
    assert "text-primary" not in approve


def test_shared_shell_structure_present_once_per_button(rendered: str) -> None:
    save = _button_holding(rendered, "Save")
    for bit in ("inline-flex", "items-center", "gap-2", "font-medium", "whitespace-nowrap"):
        assert bit in save


def test_default_size_segment(rendered: str) -> None:
    assert "px-5 py-2.5 min-h-11 text-sm rounded-[0.5rem]" in _button_holding(rendered, "Save")


def test_small_and_large_size_segments(rendered: str) -> None:
    assert "px-3.5 py-2 min-h-9 text-xs rounded-md" in _button_holding(rendered, "New release")
    assert "px-7 py-3.5 min-h-12 text-base rounded-[0.625rem]" in _button_holding(rendered, "Big submit")


def test_size_and_variant_segments_never_conflict(rendered: str) -> None:
    small = _button_holding(rendered, "New release")
    assert "px-5" not in small
    assert "min-h-11" not in small


def test_attrs_pass_through_variant_and_base_untouched(rendered: str) -> None:
    small = _button_holding(rendered, "New release")
    assert 'hx-get="/probe"' in small
    assert '@click.stop="fire()"' in small
    assert "w-full" in small


def test_slot_carries_nested_markup(rendered: str) -> None:
    assert '<i class="fas fa-plus" aria-hidden="true"></i> <span>New release</span>' in rendered


def test_submit_type_reaches_the_shell(rendered: str) -> None:
    assert 'type="submit"' in _button_holding(rendered, "Big submit")


def test_loading_disables_and_shows_the_brand_loader(rendered: str) -> None:
    loading = _button_holding(rendered, "Saving")
    assert "pointer-events-none opacity-80" in loading
    assert "disabled" in loading
    assert "tw-loader-inline" in loading


def test_disabled_prop_disables_the_shell(rendered: str) -> None:
    assert "disabled" in _button_holding(rendered, "Frozen")


def test_icon_button_variant_size_label_and_stretch_segments(rendered: str) -> None:
    actions = _button_holding(rendered, 'aria-label="Product actions"')
    assert "w-9 h-9 text-sm rounded-md" in actions
    assert "color-mix(in_oklab,var(--color-danger)_12%,transparent)" in actions
    assert '@click="menu()"' in actions
    stretchy = _button_holding(rendered, 'aria-label="Stretchy"')
    assert "w-12 h-full min-h-10" in stretchy
    assert "hover:scale-105" not in stretchy


def test_icon_button_with_href_renders_an_anchor(rendered: str) -> None:
    anchors = [part for part in rendered.split("<a ") if 'aria-label="Download artifact"' in part]
    assert anchors, "the icon button's href branch did not render an anchor"
    anchor = anchors[0].split(">")[0]
    assert 'href="/sbom/download/1"' in anchor
    assert "w-9 h-9 text-sm rounded-md" in anchor
    assert "bg-[color-mix(in_oklab,var(--color-primary)_10%,transparent)] text-primary" in anchor
    # An anchor cannot be disabled, so the affordance stays on the button branch.
    assert "disabled" not in anchor
    assert " download" in anchor


def test_variant_with_href_renders_an_anchor(rendered: str) -> None:
    anchors = [part for part in rendered.split("<a ") if "All releases" in part]
    assert anchors, "href variant did not render an anchor"
    anchor = anchors[0]
    assert 'href="/releases/new"' in anchor
    assert "hover:bg-surface" in anchor
    assert "px-3.5 py-2 min-h-9" in anchor
    assert 'target="_blank"' in anchor
    assert "disabled" not in anchor.split(">")[0]
