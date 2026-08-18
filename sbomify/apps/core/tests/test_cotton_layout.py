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
FORM_SECTION = "grid gap-y-4 gap-x-12 py-8"
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


def test_avatar_mark_is_the_avatar_component_wearing_the_icon(rendered: str) -> None:
    mark = _classes(rendered, "relative flex items-center justify-center shrink-0", "fas fa-cube")
    assert "rounded-full" in mark
    assert "w-14 h-14 text-lg" in mark
    assert "var(--avatar-accent,var(--color-primary))" in mark
    assert "w-12 h-12" not in mark


def test_meta_slot_sits_on_the_title_line(rendered: str) -> None:
    row = rendered[rendered.index("Acme Registry") :]
    row = row[: row.index("</div>")]
    assert 'data-probe="header-meta"' in row
    assert "text-danger" in row


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
    assert _classes(rendered, "text-sm text-text-muted mt-1", "Products</a>") == "text-sm text-text-muted mt-1"
    assert "Products</a>" in rendered
    assert "Acme Vault</span>" in rendered


def test_copy_values_render_beside_the_title(rendered: str) -> None:
    assert "DLyQjCBkNJkB" in rendered
    # The identifier chip is c-inline-copy, which confirms from a data attribute.
    assert 'data-copied="false"' in rendered
    assert "font-mono text-[0.8125rem] text-text bg-background" in rendered


def test_editable_params_render_the_inline_field_instead_of_plain_text(rendered: str) -> None:
    assert "editableSingleField({ itemType: 'product', itemId: 'probe-product'" in rendered


# ── Section header and body ────────────────────────────────────────────────


def test_section_header_shell_and_parts(rendered: str) -> None:
    assert _classes(rendered, SECTION_HEADER, "Generate a new token") == SECTION_HEADER
    assert '<h3 class="text-base font-semibold text-text m-0">Generate a new token</h3>' in rendered
    assert '<p class="text-sm leading-[1.5] text-text-muted mt-0.5">Tokens are shown once' in rendered


def test_section_header_chip_is_the_icon_chip_at_its_small_size(rendered: str) -> None:
    chip = _classes(rendered, "shrink-0 flex items-center justify-center w-8 h-8", "fas fa-plus-circle")
    assert "text-sm rounded-md" in chip


def test_level_two_swaps_the_heading_element(rendered: str) -> None:
    assert '<h2 class="text-base font-semibold text-text m-0">Pending invitations</h2>' in rendered
    assert '<h3 class="text-base font-semibold text-text m-0">Pending invitations' not in rendered


def test_section_header_actions_sit_after_the_title_block(rendered: str) -> None:
    """The action follows the title block rather than the chip, and the title
    block only claims the free space when there is an action to push against."""
    header = rendered.index('data-probe="section-actioned"')
    assert rendered.index("Entities", header) < rendered.index("Add entity", header)
    assert '<div class="flex-1">' in rendered[header : rendered.index("Add entity", header)]


def test_section_header_without_actions_leaves_the_title_block_unstretched(rendered: str) -> None:
    plain = rendered.index("Generate a new token")
    assert "flex-1" not in rendered[rendered.rindex(SECTION_HEADER, 0, plain) : plain]


def test_section_header_accent_reaches_the_chip(rendered: str) -> None:
    chip = _classes(rendered, "shrink-0 flex items-center justify-center w-8 h-8", "fas fa-envelope-open-text")
    assert "bg-[color-mix(in_oklab,var(--color-success)_12%,transparent)] text-success" in chip


def test_section_body_indents_to_the_titles_edge_and_merges_caller_class(rendered: str) -> None:
    body = _classes(rendered, SECTION_BODY, "Indented to the title's left edge.")
    assert body == f"{SECTION_BODY} space-y-3"


# ── Form section ───────────────────────────────────────────────────────────


def test_form_section_is_two_columns_above_the_breakpoint(rendered: str) -> None:
    section = _classes(rendered, FORM_SECTION, "What it is")
    assert "lg:grid-cols-[15rem_minmax(0,1fr)]" in section


def test_form_section_draws_the_rule_above_itself_and_the_first_drops_it(rendered: str) -> None:
    """The separator is each step's own top border, so the leading one is
    removed by position rather than by a prop the caller keeps in step."""
    section = _classes(rendered, FORM_SECTION, "What it is")
    assert "border-t border-solid border-border" in section
    assert "first-of-type:border-t-0 first-of-type:pt-0" in section


def test_form_section_title_and_description_recipes(rendered: str) -> None:
    assert '<h2 class="flex items-center gap-2.5 text-base leading-[1.5] font-semibold text-text m-0">' in rendered
    assert '<p class="text-sm leading-[1.5] text-text-muted mt-1.5">A title is all a draft needs.</p>' in rendered


def test_form_section_step_number_rides_the_small_icon_chip(rendered: str) -> None:
    chip = _classes(rendered, "shrink-0 flex items-center justify-center w-8 h-8", "What it is")
    assert "text-sm rounded-md" in chip
    assert "var(--chip-accent,var(--color-primary))" in chip
    # The number is the chip's content, not a prop it renders beside itself.
    marker = _opening(rendered, "shrink-0 flex items-center justify-center w-8 h-8", "What it is")
    assert "1" in marker.rsplit("</span>", 1)[0]


def test_form_section_icon_replaces_the_number_and_accent_reaches_the_chip(rendered: str) -> None:
    chip = _classes(rendered, "shrink-0 flex items-center justify-center w-8 h-8", "fas fa-list-check")
    assert "bg-[color-mix(in_oklab,var(--color-text-muted)_12%,transparent)] text-text-muted" in chip


def test_form_section_without_a_mark_renders_no_chip(rendered: str) -> None:
    heading = rendered[rendered.index('data-probe="form-section-bare"') : rendered.index("No mark")]
    assert "w-8 h-8" not in heading


def test_form_section_merges_caller_class_and_forwards_attrs(rendered: str) -> None:
    assert "max-w-5xl" in _classes(rendered, FORM_SECTION, "What it affects")
    assert 'data-probe="form-section-step"' in _opening(rendered, FORM_SECTION, "What it is")


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
    assert _classes(rendered, "block text-sm leading-[1.5] font-medium text-text mb-2", "Severity")
    assert '<span class="text-danger">*</span>' in rendered
    assert _classes(rendered, "block text-xs leading-[1.5] text-text-muted mt-1.5", "Pick the band")
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


def test_bound_tile_drives_the_real_control_not_a_class(rendered: str) -> None:
    """A tile the browser resolves binds the input; the look still comes from :has()."""
    tile = _opening(rendered, CHOICE, "<span>Satisfied</span>")
    # Autoescaping writes the quotes as entities; the browser hands Alpine the
    # decoded attribute, so the binding still reads `'finding-' + finding.id`.
    assert ':name="&#x27;finding-&#x27; + finding.id"' in tile
    assert 'name=""' not in tile
    assert ':checked="state(finding) === &#x27;satisfied&#x27;"' in tile
    assert '@click="setStatus(finding, &#x27;satisfied&#x27;)"' in tile
    assert ":class" not in tile


def test_bound_tile_puts_label_bindings_on_the_label(rendered: str) -> None:
    """style and title describe the tile, so they stay on the label with attrs."""
    label = _opening(rendered, CHOICE, "<span>N/A</span>")
    opening = label[: label.index("<input")]
    assert ":style=" in opening
    assert "--choice-accent: var(--color-warning)" in opening
    assert ':title="finding.hint"' in opening
    assert ':disabled="finding.is_mandatory"' in label
    assert ':disabled="finding.is_mandatory"' not in opening


def test_an_unbound_tile_emits_no_alpine_attributes(rendered: str) -> None:
    tile = _opening(rendered, CHOICE, "<span>Public</span>")
    assert ":name=" not in tile
    assert ":checked=" not in tile


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


def test_toggle_ref_points_the_row_click_at_its_own_switch(rendered: str) -> None:
    """A row whose body holds inputs of its own must not toggle the first of them."""
    opening = _opening(rendered, SELECT_ROW, "OSV Vulnerability Scanner")
    assert "$event.target.closest('a, button, select, input, textarea, label')" in opening
    assert "$refs.toggle.click()" in opening
    assert "$el.querySelector('input')" not in opening
    assert 'x-data="{ enabled: false }"' in opening


def test_disabled_dims_the_row_while_the_control_blocks_it(rendered: str) -> None:
    assert "opacity-50 grayscale" in _classes(rendered, SELECT_ROW, "Dependency Track")
    row = rendered[rendered.index("Dependency Track") :]
    assert 'id="probe-row-2"' in row.split("</div>")[0]
    assert "disabled" in row.split("</div>")[0]


def test_the_control_and_the_body_stay_in_the_slot(rendered: str) -> None:
    row = rendered[rendered.index("BSI TR-03183-2") :]
    assert '<input type="checkbox" id="probe-row-1"' in row
    assert 'for="probe-row-1"' in rendered


def _layout_probe(rendered: str, name: str) -> str:
    """The element carrying data-probe=name, from its tag open to the next one."""
    marker = f'data-probe="{name}"'
    assert marker in rendered, f"probe {name} missing"
    start = rendered.rindex("<", 0, rendered.index(marker))
    return rendered[start : rendered.index(">", rendered.index(marker)) + 1]


def test_action_tile_with_href_is_an_anchor_and_carries_its_accent(rendered: str) -> None:
    tile = _layout_probe(rendered, "tile-link")
    assert tile.startswith("<a ")
    assert 'href="/upload"' in tile
    # One prop drives the tint: the hover fill, the hover border, the hovered
    # title and the nested chip all read these two properties.
    assert "[--tile-accent:var(--color-success)]" in tile
    assert "[--chip-accent:var(--color-success)]" in tile
    assert "hover:bg-[color-mix(in_oklab,var(--tile-accent)_5%,transparent)]" in tile


def test_action_tile_without_href_is_a_button_and_keeps_its_handler(rendered: str) -> None:
    tile = _layout_probe(rendered, "tile-button")
    assert tile.startswith("<button ")
    assert '@click="open()"' in tile
    # No accent named, so the primary recipe is the resting one.
    assert "[--tile-accent:var(--color-primary)]" in tile


def test_action_tile_disabled_is_neither_a_link_nor_a_control(rendered: str) -> None:
    tile = _layout_probe(rendered, "tile-disabled")
    assert tile.startswith("<div ")
    assert "cursor-not-allowed" in tile
    assert "opacity-60" in tile
    # The trailing slot replaces the chevron with whatever says why.
    disabled_block = rendered[rendered.index('data-probe="tile-disabled"') :][:1400]
    assert "Soon" in disabled_block
    assert "fa-chevron-right" not in disabled_block


def test_data_box_puts_the_binding_on_the_value_not_a_span(rendered: str) -> None:
    bound = rendered[rendered.index('data-probe="databox-bound"') :][:400]
    assert "px-3 py-2 rounded-lg bg-border/10 border border-border/30" in _layout_probe(rendered, "databox-bound")
    assert 'x-text="fmt(item.released)"' in bound
    assert '<div class="text-xs text-text-muted">Release</div>' in bound


def test_data_box_renders_a_static_value_from_the_slot(rendered: str) -> None:
    static = rendered[rendered.index('data-probe="databox-static"') :][:400]
    assert "1.4.0" in static
    assert "x-text" not in static.split("</div>")[1]
