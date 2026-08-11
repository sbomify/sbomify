"""Render contract for the cotton layout component set.

The probe template exercises every component in components/layout; these tests
pin the page and section header shells, the stat card's parts and the custom
properties they hand each other, and the two components whose state is painted
from the control itself (the choice tile and the selectable row), so pages can
rely on them without ever writing a class themselves.
"""

import pytest
from django.template.loader import render_to_string

PAGE_HEADER = "flex flex-wrap items-start justify-between gap-4"
PAGE_ACTIONS = "flex flex-wrap items-center gap-2"
SECTION_HEADER = "flex items-start gap-3 mb-4"
SECTION_BODY = "sm:ml-11"
STAT_CARD = "flex flex-col bg-surface rounded-xl"
STAT_ICON = "shrink-0 flex items-center justify-center w-10 h-10"
STAT_LABEL = "block text-xs font-semibold uppercase"
STAT_VALUE = "block text-4xl font-bold leading-none"
STAT_ROW = "flex items-baseline gap-2.5"
STAT_CHANGE = "inline-flex items-baseline gap-1 text-[0.8125rem]"
CHOICE = "inline-flex items-center gap-2 px-3 py-2 rounded-[0.625rem]"
CHOICE_GROUP = "flex flex-wrap gap-2"
SELECT_ROW = "flex items-start gap-4 p-4 cursor-pointer"

# The lists a view builds for these components, so the probe exercises the
# options loop, the breadcrumb trail and the copyable identifiers as a page
# would hand them over.
PROBE_CONTEXT = {
    "probe_breadcrumbs": [{"label": "Products", "url": "/products"}, {"label": "Acme Vault"}],
    "probe_copy_values": [{"value": "DLyQjCBkNJkB", "title": "Product ID"}],
    "probe_choices": [
        {
            "value": "critical",
            "label": "Critical",
            "icon": "fas fa-triangle-exclamation",
            "variant": "severity-critical",
        },
        {"value": "medium", "label": "Medium", "icon": "fas fa-angle-up", "variant": "severity-medium"},
        {"value": "low", "label": "Low", "icon": "fas fa-angle-down", "variant": "severity-low", "disabled": True},
    ],
}


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string("core/cotton_probes/layout.html.j2", PROBE_CONTEXT)


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


# ── Page header ────────────────────────────────────────────────────────────


def test_page_header_shell_carries_the_gap_under_the_title(rendered: str) -> None:
    header = _classes(rendered, PAGE_HEADER, "Acme Gateway")
    assert header == f"{PAGE_HEADER} mb-6"


def test_flush_replaces_the_gap_rather_than_stacking_on_it(rendered: str) -> None:
    header = _classes(rendered, PAGE_HEADER, "Flush header")
    assert "mb-0" in header
    assert "mb-6" not in header
    assert "max-w-3xl" in header


def test_page_header_title_and_subtitle_recipes(rendered: str) -> None:
    assert '<h1 class="text-2xl leading-[1.5] font-bold tracking-[-0.02em] text-text m-0">' in rendered
    assert (
        '<p class="text-sm leading-[1.5] text-text-muted mt-1">Quantum readiness across all components.</p>'
    ) in rendered


def test_chip_mark_is_the_icon_chip_at_its_large_size(rendered: str) -> None:
    chip = _classes(rendered, "shrink-0 flex items-center justify-center w-12 h-12", "fas fa-box")
    assert "text-lg rounded-[0.625rem]" in chip
    assert "var(--chip-accent,var(--color-primary))" in chip


def test_avatar_mark_replaces_the_chip(rendered: str) -> None:
    mark = _classes(rendered, "relative shrink-0 flex items-center justify-center", "fas fa-cube")
    assert "w-14 h-14 rounded-full" in mark
    assert "var(--avatar-accent,var(--color-primary))" in mark
    assert "w-12 h-12" not in mark


def test_actions_render_only_when_the_slot_has_content(rendered: str) -> None:
    assert rendered.count(f'{PAGE_ACTIONS}"') == 1
    actions = rendered[rendered.index(PAGE_ACTIONS) :]
    assert "Assign component" in actions.split("</div>")[0]


def test_page_header_forwards_attrs(rendered: str) -> None:
    opening = _opening(rendered, PAGE_HEADER, "Acme Gateway")
    assert 'hx-get="/probe/header"' in opening
    assert 'data-probe="page-header"' in opening


def test_breadcrumbs_replace_the_subtitle(rendered: str) -> None:
    assert 'aria-label="Breadcrumb"' in rendered
    assert _classes(rendered, "text-sm text-text-muted mt-1", ">Products</a>") == "text-sm text-text-muted mt-1"
    assert ">Products</a>" in rendered
    assert ">Acme Vault</span>" in rendered


def test_copy_values_render_beside_the_title(rendered: str) -> None:
    assert "DLyQjCBkNJkB" in rendered
    assert "tw-inline-copy" in rendered


def test_editable_params_render_the_inline_field_instead_of_plain_text(rendered: str) -> None:
    assert "editableSingleField({ itemType: 'product', itemId: 'probe-product'" in rendered


# ── Section header and body ────────────────────────────────────────────────


def test_section_header_shell_and_parts(rendered: str) -> None:
    assert _classes(rendered, SECTION_HEADER, "Generate a new token") == SECTION_HEADER
    assert '<h3 class="text-base font-semibold text-text m-0">Generate a new token</h3>' in rendered
    assert '<p class="text-sm text-text-muted mt-0.5">Tokens are shown once' in rendered


def test_section_header_chip_is_the_icon_chip_at_its_small_size(rendered: str) -> None:
    chip = _classes(rendered, "shrink-0 flex items-center justify-center w-8 h-8", "fas fa-plus-circle")
    assert "text-sm rounded-md" in chip


def test_level_two_swaps_the_heading_element(rendered: str) -> None:
    assert '<h2 class="text-base font-semibold text-text m-0">Pending invitations</h2>' in rendered
    assert '<h3 class="text-base font-semibold text-text m-0">Pending invitations' not in rendered


def test_section_header_accent_reaches_the_chip(rendered: str) -> None:
    chip = _classes(rendered, "shrink-0 flex items-center justify-center w-8 h-8", "fas fa-envelope-open-text")
    assert "bg-[color-mix(in_oklab,var(--color-success)_12%,transparent)] text-success" in chip


def test_section_body_indents_to_the_titles_edge_and_merges_caller_class(rendered: str) -> None:
    body = _classes(rendered, SECTION_BODY, "Indented to the title's left edge.")
    assert body == f"{SECTION_BODY} space-y-3"


# ── Stat card ──────────────────────────────────────────────────────────────


def test_stat_card_surface_and_padding(rendered: str) -> None:
    card = _classes(rendered, STAT_CARD, "Total products")
    assert "border border-solid border-border shadow-[var(--shadow-card)]" in card
    assert "px-6 py-5" in card


def test_compact_replaces_the_padding_and_retunes_the_parts(rendered: str) -> None:
    card = _classes(rendered, STAT_CARD, "Ready")
    assert "px-4 py-3 items-center text-center" in card
    assert "px-6" not in card
    assert "py-5" not in card
    assert "[--stat-value-color:var(--stat-accent,var(--color-text))]" in card
    assert "[--stat-label-mt:0.25rem] [--stat-label-mb:0px]" in card


@pytest.mark.parametrize(
    ("marker", "token"),
    [("Vulnerabilities", "danger"), ("Stale scans", "warning"), ("Ready", "success")],
)
def test_accent_sets_exactly_one_custom_property(rendered: str, marker: str, token: str) -> None:
    card = _classes(rendered, STAT_CARD, marker)
    assert f"[--stat-accent:var(--color-{token})]" in card
    assert card.count("[--stat-accent:") == 1


def test_a_card_with_no_accent_leaves_the_property_unset(rendered: str) -> None:
    assert "[--stat-accent:" not in _classes(rendered, STAT_CARD, "Total products")


def test_stat_icon_takes_the_cards_accent(rendered: str) -> None:
    icon = _classes(rendered, STAT_ICON, "fas fa-shield-halved")
    assert "mb-1.5 rounded-[0.625rem]" in icon
    assert "bg-[color-mix(in_oklab,var(--stat-accent,var(--color-primary))_12%,transparent)]" in icon
    assert "text-[color:var(--stat-accent,var(--color-primary))]" in icon


def test_stat_label_and_value_recipes(rendered: str) -> None:
    label = _classes(rendered, STAT_LABEL, "Total products")
    assert "tracking-[0.06em] text-text-muted" in label
    assert "mt-[var(--stat-label-mt,0px)] mb-[var(--stat-label-mb,0.5rem)]" in label
    value = _classes(rendered, STAT_VALUE, "1,234")
    assert "tracking-[-0.03em] tabular-nums" in value
    assert "text-[color:var(--stat-value-color,var(--color-text))]" in value


@pytest.mark.parametrize(
    ("marker", "token"),
    [("fas fa-arrow-up", "success"), ("fas fa-arrow-down", "danger")],
)
def test_change_variants_carry_their_ink(rendered: str, marker: str, token: str) -> None:
    change = _classes(rendered, STAT_CHANGE, marker)
    assert f"text-[color-mix(in_oklab,var(--color-{token})_70%,var(--color-text))]" in change


def test_the_row_drops_the_changes_top_margin_and_a_bare_change_keeps_it(rendered: str) -> None:
    assert "[--stat-change-mt:0px]" in _classes(rendered, STAT_ROW, "1,234")
    bare = _classes(rendered, STAT_CHANGE, "unchanged")
    assert "mt-[var(--stat-change-mt,0.5rem)]" in bare
    assert "color-mix" not in bare


def test_stat_card_forwards_attrs_and_caller_class(rendered: str) -> None:
    assert "lg:col-span-2" in _classes(rendered, STAT_CARD, "Stale scans")
    assert '@click="drill()"' in _opening(rendered, STAT_CARD, "Stale scans")


# ── Choice group and choice ────────────────────────────────────────────────


def test_choice_group_label_and_hint_come_from_the_form_field(rendered: str) -> None:
    assert _classes(rendered, "block text-sm font-medium text-text mb-2", "Severity")
    assert '<span class="text-danger">*</span>' in rendered
    assert _classes(rendered, "block text-xs text-text-muted mt-1.5", "Pick the band")
    assert ">Pick the band it reports under." in rendered


def test_the_group_carries_the_radio_role_and_the_accessible_name(rendered: str) -> None:
    opening = _opening(rendered, CHOICE_GROUP, 'data-probe="choice-options"')
    assert 'role="radiogroup"' in opening
    assert 'aria-label="Severity"' in opening


@pytest.mark.parametrize(
    ("marker", "token"),
    [
        ("Critical", "severity-critical"),
        ("Medium", "severity-medium"),
        ("Low", "severity-low"),
        ("Public", "info"),
        ("Private", "text-muted"),
    ],
)
def test_each_option_wears_its_accent_as_one_property(rendered: str, marker: str, token: str) -> None:
    tile = _classes(rendered, CHOICE, f"<span>{marker}</span>")
    assert f"[--choice-accent:var(--color-{token})]" in tile
    assert tile.count("[--choice-accent:") == 1


def test_selection_is_painted_from_the_control_not_from_a_class(rendered: str) -> None:
    tile = _classes(rendered, CHOICE, "<span>Medium</span>")
    assert "has-[:checked]:border-[color:var(--choice-accent,var(--color-primary))]" in tile
    assert "has-[:checked]:bg-[color-mix(in_oklab,var(--choice-accent,var(--color-primary))_12%,transparent)]" in tile
    assert "has-[:focus-visible]:shadow-[0_0_0_2px_color-mix(in_oklab,var(--color-primary)_45%,transparent)]" in tile
    assert "has-[:disabled]:opacity-50 has-[:disabled]:cursor-not-allowed" in tile
    # The tint only ever arrives through the :has() variant, never bare.
    assert " bg-[color-mix" not in tile


def test_only_the_option_matching_selected_is_checked(rendered: str) -> None:
    group = rendered[rendered.index('data-probe="choice-options"') : rendered.index("Pick the band")]
    controls = [chunk[: chunk.index(">")] for chunk in group.split("<input")[1:]]
    assert len(controls) == 3
    checked = [control for control in controls if "checked" in control]
    assert len(checked) == 1
    assert 'value="medium"' in checked[0]


def test_option_flags_reach_the_real_control(rendered: str) -> None:
    tile = _opening(rendered, CHOICE, "<span>Low</span>")
    assert "disabled" in tile
    assert "required" in tile
    assert 'type="radio"' in tile
    assert 'name="probe-severity"' in tile
    assert 'class="absolute w-px h-px opacity-0 pointer-events-none"' in tile


def test_choice_icon_takes_the_tiles_accent(rendered: str) -> None:
    assert '<i class="fas fa-angle-up text-sm text-[color:var(--choice-accent,var(--color-text-muted))]"' in rendered


def test_a_group_without_options_renders_its_tiles_from_the_slot(rendered: str) -> None:
    group = rendered[rendered.index('name="probe-visibility"') :]
    assert "<span>Public</span>" in group
    assert "<span>Private</span>" in group
    assert "max-w-md" in _classes(rendered, "space-y-1.5", "<span>Public</span>")


# ── Selectable row ─────────────────────────────────────────────────────────


def test_select_row_recipe_and_its_state_variants(rendered: str) -> None:
    row = _classes(rendered, SELECT_ROW, "BSI TR-03183-2")
    assert "transition-colors duration-150" in row
    assert "hover:bg-[color-mix(in_oklab,var(--color-primary)_6%,transparent)]" in row
    assert "has-[:checked]:bg-[color-mix(in_oklab,var(--color-primary)_4%,transparent)]" in row
    assert "has-[:checked]:hover:bg-[color-mix(in_oklab,var(--color-primary)_9%,transparent)]" in row
    assert "has-[:focus-visible]:bg-[color-mix(in_oklab,var(--color-primary)_8%,transparent)]" in row
    assert "has-[input:disabled]:cursor-not-allowed has-[input:disabled]:hover:bg-transparent" in row


def test_the_row_click_is_a_convenience_that_stands_aside(rendered: str) -> None:
    opening = _opening(rendered, SELECT_ROW, "BSI TR-03183-2")
    assert "$event.target.closest('a, button, select, input, textarea, label')" in opening
    assert "$el.querySelector('input')?.click()" in opening
    assert "x-data\n" in opening or "x-data " in opening


def test_alpine_state_arrives_as_one_scope(rendered: str) -> None:
    opening = _opening(rendered, SELECT_ROW, "CNSA 2.0")
    assert 'x-data="{ showDeleteModal: false }"' in opening
    assert opening.count("x-data") == 1
    assert 'hx-get="/probe/row"' in opening
    assert '@keydown.enter="open()"' in opening
    assert "rounded-b-xl" in _classes(rendered, SELECT_ROW, "CNSA 2.0")


def test_disabled_dims_the_row_while_the_control_blocks_it(rendered: str) -> None:
    assert "opacity-50 grayscale" in _classes(rendered, SELECT_ROW, "Dependency Track")
    row = rendered[rendered.index("Dependency Track") :]
    assert 'id="probe-row-2"' in row.split("</div>")[0]
    assert "disabled" in row.split("</div>")[0]


def test_the_control_and_the_body_stay_in_the_slot(rendered: str) -> None:
    row = rendered[rendered.index("BSI TR-03183-2") :]
    assert '<input type="checkbox" id="probe-row-1"' in row
    assert 'for="probe-row-1"' in rendered
