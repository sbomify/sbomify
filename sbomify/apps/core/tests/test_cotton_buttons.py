"""Render contract for the cotton buttons component set.

The probe template exercises every component in components/buttons; these
tests pin the emitted markup to the same classes the tag-layer macros emit,
so a page can swap between the two without a pixel moving.
"""

import pytest
from django.template.loader import render_to_string


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string("core/cotton_probes/buttons.html.j2")


@pytest.mark.parametrize(
    "variant",
    ["primary", "secondary", "ghost", "gradient", "success", "warning", "danger"],
)
def test_filled_variants_emit_macro_identical_classes(rendered: str, variant: str) -> None:
    assert f'class="tw-btn tw-btn-{variant}"' in rendered


@pytest.mark.parametrize(
    "variant",
    ["outline", "outline-primary", "outline-warning", "outline-danger"],
)
def test_outline_variants_resolve_snake_cased_files(rendered: str, variant: str) -> None:
    assert f'class="tw-btn tw-btn-{variant}"' in rendered


def test_size_class_and_layout_class_merge_after_variant(rendered: str) -> None:
    assert 'class="tw-btn tw-btn-primary tw-btn-sm w-full"' in rendered
    assert 'class="tw-btn tw-btn-secondary tw-btn-lg"' in rendered


def test_attrs_pass_through_variant_and_base_untouched(rendered: str) -> None:
    assert 'hx-get="/probe"' in rendered
    assert '@click.stop="fire()"' in rendered


def test_slot_carries_nested_markup(rendered: str) -> None:
    assert '<i class="fas fa-plus" aria-hidden="true"></i> <span>New release</span>' in rendered


def test_submit_type_reaches_the_shell(rendered: str) -> None:
    assert 'type="submit"' in rendered


def test_loading_adds_class_spinner_and_disables(rendered: str) -> None:
    assert "tw-btn-loading" in rendered
    assert "tw-loader-inline" in rendered
    loading_button = rendered.split("tw-btn-loading")[0].rsplit("<button", 1)[1]
    assert "disabled" in loading_button + rendered.split("tw-btn-loading")[1][:200]


def test_disabled_prop_disables_the_shell(rendered: str) -> None:
    frozen = [part for part in rendered.split("<button") if "Frozen" in part][0]
    assert "disabled" in frozen


def test_icon_button_carries_label_variant_size_and_stretch(rendered: str) -> None:
    actions = [part for part in rendered.split("<button") if "Product actions" in part][0]
    assert 'class="tw-icon-btn tw-icon-btn-danger tw-icon-btn-sm"' in actions
    assert 'aria-label="Product actions"' in actions
    assert '@click="menu()"' in actions
    stretchy = [part for part in rendered.split("<button") if "Stretchy" in part][0]
    assert "tw-icon-btn-stretch" in stretchy


def test_link_renders_anchor_with_button_classes_and_safe_target(rendered: str) -> None:
    anchor = [part for part in rendered.split("<a ") if "All releases" in part][0]
    assert 'href="/releases/new"' in anchor
    assert "tw-btn tw-btn-ghost tw-btn-sm" in anchor
    assert 'target="_blank" rel="noopener noreferrer"' in anchor
