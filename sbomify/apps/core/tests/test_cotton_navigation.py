"""Render contract for the cotton navigation component set.

The probe template exercises every component in components/navigation; these
tests pin the tab row and its tabs, the crumb trail, the pager and its cells,
the stepper parts and the accordion, so pages can rely on the components
without ever writing a class themselves.
"""

import pytest
from django.template.loader import render_to_string

TAB = "relative px-5 py-3.5 text-sm font-medium border-b-2 border-solid -mb-px"
CELL = "flex items-center justify-center min-w-8 h-8 px-2 rounded-md border border-solid border-transparent"
CIRCLE = "relative shrink-0 flex items-center justify-center w-10 h-10 rounded-full"
TRIGGER = "group flex w-full items-center justify-between px-6 py-5 text-left"
RAIL = "flex-1 h-[3px] mx-4 rounded-full overflow-hidden"
VERTICAL_RAIL = "[[data-stepper-vertical]_&]:w-[3px]"

PROBE_CONTEXT = {
    "probe_tabs": [
        {"id": "overview", "label": "Overview", "icon": "fas fa-chart-line"},
        {"id": "sboms", "label": "SBOMs", "icon": "fas fa-file-code", "badge": "12"},
        {"id": "documents", "label": "Documents"},
    ],
    "probe_crumbs": [
        {"label": "Products", "url": "/products"},
        {"label": "Acme Widget", "url": "/products/1"},
        {"label": "Releases"},
    ],
    "probe_marked_crumbs": [
        {"label": "Trust Center", "url": "/public/workspace/acme", "icon": "fas fa-shield-alt"},
        {"label": "Acme Widget", "url": "/public/product/1", "icon": "fas fa-box", "title": "Acme Widget 2026"},
    ],
    "probe_page_range": [1, 2, 3, "…", 8],
    "probe_single_page": [1],
    "probe_short_range": [1, 2, 3, 4],
}


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string("core/cotton_probes/navigation.html.j2", PROBE_CONTEXT)


def _chunk(rendered: str, tag: str, marker: str) -> str:
    """The markup of the first `tag` element that holds `marker`."""
    chunks = [part for part in rendered.split(f"<{tag}") if marker in part]
    assert chunks, f"no <{tag}> holds {marker!r}"
    return chunks[0]


def _open_tag(rendered: str, tag: str, marker: str) -> str:
    """The opening `tag` whose own attributes hold `marker`, attributes and all."""
    at = rendered.index(marker)
    start = rendered.rindex(f"<{tag}", 0, at)
    return rendered[start : rendered.index(">", at) + 1]


def _between(rendered: str, start_marker: str, end_marker: str) -> str:
    """The probe's markup from one data-probe marker up to the next one."""
    start = rendered.index(start_marker)
    return rendered[start : rendered.index(end_marker, start)]


def _classes(rendered: str, marker: str) -> str:
    """The class list of the element whose opening tag holds `marker`."""
    at = rendered.index(marker)
    start = rendered.rindex('class="', 0, at) + len('class="')
    return rendered[start : rendered.index('"', start)]


# ── Tabs ──────────────────────────────────────────────────────────────────


def test_tab_row_is_a_tablist_with_the_underline_recipe(rendered: str) -> None:
    row = _chunk(rendered, "div", 'data-probe="tabs"')
    assert 'role="tablist"' in row
    assert "flex gap-1 border-b border-solid border-border" in row


def test_tab_row_carries_the_arrow_home_and_end_keys(rendered: str) -> None:
    row = _chunk(rendered, "div", 'data-probe="tabs"')
    for handler in (
        "@keydown.arrow-right.prevent",
        "@keydown.arrow-left.prevent",
        "@keydown.home.prevent",
        "@keydown.end.prevent",
    ):
        assert handler in row
    assert "$el.querySelectorAll('[role=tab]')" in row


def test_pills_variant_swaps_the_recipe_and_marks_the_row(rendered: str) -> None:
    row = _open_tag(rendered, "div", 'data-probe="pills"')
    assert "flex gap-0 bg-background p-1 rounded-lg" in row
    assert "data-tabs-pills" in row
    assert "border-b" not in row
    assert "gap-1" not in row


def test_row_class_never_falls_through_to_its_tabs(rendered: str) -> None:
    row = _chunk(rendered, "div", 'data-probe="tabs"')
    assert row.count("mb-4") == 1


def test_selected_tab_segment(rendered: str) -> None:
    tab = _chunk(rendered, "button", "Hand built")
    assert TAB in tab
    assert "text-primary border-b-primary" in tab
    assert "text-text-muted" not in _classes(rendered, "Hand built")
    assert 'aria-selected="true"' in tab
    assert 'tabindex="0"' in tab


def test_quiet_tab_segment(rendered: str) -> None:
    tab = _chunk(rendered, "button", "Quiet tab")
    assert "text-text-muted border-b-transparent" in tab
    assert "border-b-primary" not in tab
    assert 'aria-selected="false"' in tab
    assert 'tabindex="-1"' in tab


def test_tab_points_at_the_panel_it_controls(rendered: str) -> None:
    tab = _chunk(rendered, "button", "Quiet tab")
    assert 'id="tab-quiet"' in tab
    assert 'aria-controls="panel-quiet"' in tab
    assert 'data-tab="quiet"' in tab


def test_pills_utilities_hang_off_the_row_marker(rendered: str) -> None:
    tab = _chunk(rendered, "button", "Hand built")
    for bit in (
        "[[data-tabs-pills]_&]:mb-0",
        "[[data-tabs-pills]_&]:rounded-md",
        "[[data-tabs-pills]_&]:border-b-0",
        "[[data-tabs-pills]_&]:bg-surface",
    ):
        assert bit in tab


def test_tab_icon_takes_a_gutter_only_beside_a_label(rendered: str) -> None:
    assert '<i class="fas fa-file-code mr-2" aria-hidden="true"></i>' in rendered
    icon_only = _chunk(rendered, "button", 'aria-label="Settings"')
    assert '<i class="fas fa-gear" aria-hidden="true"></i>' in icon_only


def test_tab_badge_takes_the_selected_colour(rendered: str) -> None:
    selected = _chunk(rendered, "button", "Hand built")
    assert "min-w-5 h-5 ml-2 px-1.5 text-[0.625rem] font-semibold rounded-full" in selected
    assert "bg-[color-mix(in_oklab,var(--color-primary)_15%,transparent)] text-primary" in selected
    quiet = _chunk(rendered, "button", "SBOMs")
    assert "bg-border text-text-muted" in quiet


def test_tab_forwards_attrs(rendered: str) -> None:
    tab = _chunk(rendered, "button", "Hand built")
    assert "@click=\"pick('hand')\"" in tab
    assert 'hx-get="/probe/hand"' in tab


# ── Breadcrumbs ───────────────────────────────────────────────────────────


def test_breadcrumbs_are_a_labelled_trail(rendered: str) -> None:
    crumbs = _chunk(rendered, "nav", 'data-probe="crumbs"')
    assert 'aria-label="Breadcrumb"' in crumbs
    assert '<ol class="flex items-center gap-2 text-sm">' in crumbs
    assert 'class="mb-2"' in crumbs


def test_breadcrumb_separator_sits_between_crumbs_only(rendered: str) -> None:
    crumbs = _chunk(rendered, "nav", 'data-probe="crumbs"')
    assert crumbs.count('class="fas fa-chevron-right text-xs text-text-muted"') == 2


def test_breadcrumb_links_lead_to_the_current_page_as_text(rendered: str) -> None:
    crumbs = _chunk(rendered, "nav", 'data-probe="crumbs"')
    assert '<a href="/products"' in crumbs
    assert "text-text-muted hover:text-text transition-colors" in crumbs
    current = _open_tag(rendered, "span", "Releases")
    assert 'class="text-text font-medium"' in current
    assert 'aria-current="page"' in current


def test_breadcrumb_without_icons_keeps_its_plain_labels(rendered: str) -> None:
    crumbs = _chunk(rendered, "nav", 'data-probe="crumbs"')
    assert "flex items-center gap-1" not in crumbs


def test_breadcrumb_icon_brings_its_own_row_layout(rendered: str) -> None:
    trail = _chunk(rendered, "nav", 'data-probe="marked-crumbs"')
    link = _open_tag(rendered, "a", '"/public/workspace/acme"')
    assert "text-text-muted hover:text-text transition-colors flex items-center gap-1" in link
    assert '<i class="fas fa-shield-alt opacity-80" aria-hidden="true">' in trail


def test_breadcrumb_title_names_a_shortened_label(rendered: str) -> None:
    current = _open_tag(rendered, "span", '"Acme Widget 2026"')
    assert 'title="Acme Widget 2026"' in current
    assert 'aria-current="page"' in current


# ── Pagination ────────────────────────────────────────────────────────────


def test_pager_is_a_labelled_row(rendered: str) -> None:
    pager = _open_tag(rendered, "nav", 'data-probe="pager"')
    assert 'aria-label="Pagination"' in pager
    assert "flex items-center gap-1 mt-2" in pager


def test_pager_class_never_falls_through_to_its_cells(rendered: str) -> None:
    pager = _chunk(rendered, "nav", 'data-probe="pager"')
    assert pager.count("mt-2") == 1


def test_page_links_carry_the_cell_recipe_and_their_page(rendered: str) -> None:
    link = _chunk(rendered, "a", ">1</a>")
    assert CELL in link
    assert "bg-transparent text-text-muted font-medium cursor-pointer" in link
    assert "hover:bg-surface hover:border-border hover:text-text active:scale-95" in link
    assert 'href="/components?page=1"' in link


def test_current_page_is_a_span_that_says_so(rendered: str) -> None:
    current = _chunk(rendered, "span", ">3</span>")
    assert 'aria-current="page"' in current
    assert "bg-[linear-gradient(135deg,var(--color-primary)_0%,var(--color-primary-dark)_100%)]" in current
    assert "text-white font-semibold" in current
    assert "shadow-[0_2px_4px_color-mix(in_oklab,var(--color-primary)_30%,transparent)]" in current
    classes = _classes(rendered, ">3</span>")
    assert "hover:" not in classes
    assert "text-text-muted" not in classes


def test_ellipsis_is_a_bare_cell(rendered: str) -> None:
    assert '<span class="flex items-center justify-center min-w-8 h-8 text-[0.8125rem] text-text-muted"' in rendered


def test_previous_and_next_step_one_page(rendered: str) -> None:
    pager = _between(rendered, 'data-probe="pager"', 'data-probe="single"')
    assert 'href="/components?page=2"' in pager
    assert 'href="/components?page=4"' in pager


def test_nav_cells_take_the_smaller_type_and_never_both_sizes(rendered: str) -> None:
    previous = _classes(rendered, 'aria-label="Previous page"')
    assert "text-xs" in previous
    assert "text-[0.8125rem]" not in previous


def test_a_dead_nav_cell_says_aria_disabled_not_disabled(rendered: str) -> None:
    single = _between(rendered, 'data-probe="single"', 'data-probe="numbers"')
    dead = _chunk(single, "a", 'aria-label="Previous page"')
    assert 'href="#"' in dead
    assert 'aria-disabled="true"' in dead
    assert 'tabindex="-1"' in dead
    assert "opacity-40 cursor-not-allowed" in dead
    classes = _classes(single, 'aria-label="Previous page"')
    assert "hover:" not in classes
    assert "active:scale-95" not in classes


def test_numbers_only_pager_drops_the_chevrons(rendered: str) -> None:
    numbers = _between(rendered, 'data-probe="numbers"', "Standalone link")
    assert "fa-chevron-left" not in numbers
    assert "fa-chevron-right" not in numbers
    assert 'href="/numbers?page=3"' in numbers


def test_standalone_page_link_forwards_attrs(rendered: str) -> None:
    link = _chunk(rendered, "a", "Standalone link")
    assert 'hx-boost="false"' in link
    assert CELL in link


# ── Stepper ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("marker", "recipe_bit"),
    [
        ("Scope", "bg-[linear-gradient(135deg,var(--color-success)_0%,var(--color-success-dark)_100%)] text-white"),
        (
            "Assessment",
            "bg-[linear-gradient(135deg,var(--color-primary)_0%,var(--color-primary-dark)_100%)] text-white "
            "shadow-[0_0_0_4px_color-mix(in_oklab,var(--color-primary)_20%,transparent)]",
        ),
        ("Declaration", "bg-border text-text-muted"),
    ],
)
def test_step_circle_states(rendered: str, marker: str, recipe_bit: str) -> None:
    step = _chunk(rendered, "div", marker)
    assert CIRCLE in step
    assert recipe_bit in step


def test_only_the_active_step_brightens_its_label(rendered: str) -> None:
    label = "ml-3 text-sm font-medium transition-colors duration-200"
    assert f'<span class="{label} text-text">Assessment</span>' in rendered
    assert f'<span class="{label} text-text-muted">Scope</span>' in rendered


def test_step_takes_class_and_attrs(rendered: str) -> None:
    step = _open_tag(rendered, "div", 'data-probe="step"')
    assert 'class="flex items-center ml-1"' in step


def test_label_class_lands_on_the_caption_only(rendered: str) -> None:
    """A narrow rail hides its captions; the circles and the step keep their layout."""
    assert 'text-text-muted hidden sm:inline">Declaration</span>' in rendered
    assert "hidden sm:inline" not in _open_tag(rendered, "div", 'data-probe="step"')


def test_connector_fills_only_when_completed(rendered: str) -> None:
    stepper = _between(rendered, 'data-probe="stepper"', 'data-probe="vertical"')
    rails = [part for part in stepper.split("<span") if VERTICAL_RAIL in part]
    assert len(rails) == 2
    assert RAIL in rails[0]
    assert "bg-[linear-gradient(90deg,var(--color-success)_0%,var(--color-success-dark)_100%)]" in rails[0]
    assert "bg-border" in rails[1]
    assert "linear-gradient(90deg" not in rails[1]


def test_vertical_stepper_stacks_and_marks_the_rail(rendered: str) -> None:
    rail = _open_tag(rendered, "div", 'data-probe="vertical"')
    assert "flex flex-col items-start mt-4" in rail
    assert "data-stepper-vertical" in rail
    assert "items-center" not in rail


def test_vertical_connector_utilities_hang_off_the_rail_marker(rendered: str) -> None:
    connector = _chunk(rendered, "span", "[[data-stepper-vertical]_&]:ml-[1.1875rem]")
    for bit in (
        "[[data-stepper-vertical]_&]:w-[3px]",
        "[[data-stepper-vertical]_&]:h-8",
        "[[data-stepper-vertical]_&]:my-2",
        "[[data-stepper-vertical]_&]:mr-0",
    ):
        assert bit in connector


# ── Accordion ─────────────────────────────────────────────────────────────


def test_accordion_is_one_clipped_bordered_surface(rendered: str) -> None:
    box = _open_tag(rendered, "div", 'data-probe="accordion"')
    assert "bg-surface rounded-xl overflow-hidden border border-solid border-border mb-4" in box
    assert "data-accordion-sm" not in box


def test_density_marks_the_container_and_the_items_read_it(rendered: str) -> None:
    compact = _open_tag(rendered, "div", 'data-probe="compact"')
    assert "data-accordion-sm" in compact
    trigger = _chunk(rendered, "button", "Compact section")
    assert "[[data-accordion-sm]_&]:px-4 [[data-accordion-sm]_&]:py-3 [[data-accordion-sm]_&]:text-sm" in trigger
    assert "px-6 py-5" in trigger


def test_items_are_divided_and_the_last_one_is_not(rendered: str) -> None:
    item = _chunk(rendered, "div", "Organisational controls")
    assert (
        "border-b border-solid border-[color-mix(in_oklab,var(--color-border)_50%,transparent)] last:border-b-0" in item
    )


def test_trigger_is_a_real_button_bound_to_the_open_state(rendered: str) -> None:
    trigger = _chunk(rendered, "button", "Organisational controls")
    assert 'type="button"' in trigger
    assert TRIGGER in trigger
    assert "hover:bg-[color-mix(in_oklab,var(--color-primary)_3%,transparent)]" in trigger
    assert "focus-visible:shadow-[inset_0_0_0_2px_color-mix(in_oklab,var(--color-primary)_50%,transparent)]" in trigger
    # Django escapes the quotes in the expression; the browser hands Alpine the
    # decoded attribute, so the binding still reads `open === 'org'`.
    assert ':aria-expanded="open === &#x27;org&#x27;"' in trigger
    assert "@click=\"open = open === 'org' ? '' : 'org'\"" in trigger


def test_trigger_turns_the_chevron_over_from_its_own_state(rendered: str) -> None:
    trigger = _chunk(rendered, "button", "Organisational controls")
    chevron = "fas fa-chevron-down text-text-muted transition-transform duration-300 group-aria-expanded:rotate-180"
    assert chevron in trigger


def test_label_slot_replaces_the_label_prop(rendered: str) -> None:
    trigger = _chunk(rendered, "button", "Technological controls")
    assert '<span class="flex items-center gap-2">Technological controls</span>' in trigger
    assert 'data-probe="item"' in trigger


def test_label_class_lands_on_the_label_and_nowhere_else(rendered: str) -> None:
    """A rich row reaches the trigger's full width from the label, its flex item."""
    trigger = _chunk(rendered, "button", "Technological controls")
    assert '<span class="flex flex-1 items-center justify-between gap-3 min-w-0 mr-3">' in trigger
    assert "flex-1" not in trigger[: trigger.index("<span")]
    # A label with no class of its own carries no class attribute at all.
    assert "<span >Organisational controls</span>" in _chunk(rendered, "button", "Organisational controls")


def test_panel_collapses_on_the_same_expression(rendered: str) -> None:
    panel = _chunk(rendered, "div", "Policies, roles and supplier relationships.")
    assert "px-6 pb-5 text-sm leading-[1.6] text-text-muted" in panel
    assert 'x-show="open === &#x27;org&#x27;" x-collapse' in panel


def test_a_section_without_a_state_stays_open(rendered: str) -> None:
    panel = _chunk(rendered, "div", "Always open without a state.")
    assert "x-show" not in panel
    assert ":aria-expanded" not in _chunk(rendered, "button", "Compact section")


# ── Disclosure ────────────────────────────────────────────────────────────


def test_disclosure_is_a_details_element_divided_like_an_accordion_item(rendered: str) -> None:
    section = _chunk(rendered, "details", "Configure the workflow")
    assert (
        "group border-b border-solid border-[color-mix(in_oklab,var(--color-border)_50%,transparent)] last:border-b-0"
        in section
    )
    assert 'data-probe="disclosure"' in section


def test_disclosure_summary_carries_the_trigger_recipe_and_the_density_hook(rendered: str) -> None:
    section = _chunk(rendered, "details", "Configure the workflow")
    assert "flex w-full cursor-pointer items-center justify-between px-6 py-5 text-left" in section
    assert "hover:bg-[color-mix(in_oklab,var(--color-primary)_3%,transparent)]" in section
    assert "focus-visible:shadow-[inset_0_0_0_2px_color-mix(in_oklab,var(--color-primary)_50%,transparent)]" in section
    assert "[[data-accordion-sm]_&]:px-4 [[data-accordion-sm]_&]:py-3" in section
    # The compact size is the bare font-size: text-sm would bring 1.4286 where
    # the stylesheet's compact trigger inherited 1.5.
    assert "[[data-accordion-sm]_&]:text-[0.875rem]" in section


def test_disclosure_chevron_turns_on_the_native_open_state(rendered: str) -> None:
    section = _chunk(rendered, "details", "Configure the workflow")
    chevron = "fas fa-chevron-down text-text-muted transition-transform duration-300 group-open:rotate-180"
    assert chevron in section
    assert "x-show" not in section
    assert ":aria-expanded" not in section


def test_disclosure_label_slot_and_label_class(rendered: str) -> None:
    section = _chunk(rendered, "details", "Configure the workflow")
    assert '<span class="flex items-center gap-2">' in section
    assert "flex items-center gap-2" not in section[: section.index("<summary")]


def test_disclosure_open_prop_renders_the_native_attribute(rendered: str) -> None:
    closed = _open_tag(rendered, "details", 'data-probe="disclosure"')
    opened = _open_tag(rendered, "details", 'data-probe="disclosure-open"')
    assert " open" not in closed
    assert " open" in opened


def _nav_probe(rendered: str, name: str) -> str:
    marker = f'data-probe="{name}"'
    assert marker in rendered, f"probe {name} missing"
    start = rendered.rindex("<", 0, rendered.index(marker))
    return rendered[start : rendered.index(">", rendered.index(marker)) + 1]


def test_page_button_states_hang_off_data_active_and_disabled(rendered: str) -> None:
    btn = _nav_probe(rendered, "page-btn")
    assert btn.startswith("<button ")
    assert 'data-active="false"' in btn
    assert "data-[active=true]:text-white" in btn
    assert "disabled:opacity-40" in btn


def test_page_button_nav_segment_and_label(rendered: str) -> None:
    nav = _nav_probe(rendered, "page-btn-nav")
    assert "text-xs" in nav
    assert 'aria-label="Previous page"' in nav


def test_page_ellipsis_is_not_a_control(rendered: str) -> None:
    ell = _nav_probe(rendered, "page-ellipsis")
    assert ell.startswith("<span ")
    assert 'aria-hidden="true"' in ell


# ── Filtered pager and segmented control ──────────────────────────────────


def test_filtered_pager_keeps_its_filters_and_takes_its_own_name(rendered: str) -> None:
    pager = _open_tag(rendered, "nav", 'data-probe="filtered"')
    assert 'aria-label="Scan pagination"' in pager
    filtered = rendered[rendered.index('data-probe="filtered"') : rendered.index('data-probe="segmented"')]
    # Previous, next and every numbered link keep the filter; the current page
    # is a span, so it carries no query at all. The separator is an entity
    # because it is interpolated, which is the escaping the URL wants anyway.
    assert 'href="?page=1&amp;days=30"' in filtered
    assert 'href="?page=3&amp;days=30"' in filtered
    assert 'href="?page=4&amp;days=30"' in filtered
    assert filtered.count("days=30") == 5
    assert "?page=2" not in filtered


def test_unfiltered_pager_links_carry_no_stray_separator(rendered: str) -> None:
    pager = _between(rendered, 'data-probe="pager"', 'data-probe="single"')
    assert "&amp;" not in pager


def test_segmented_is_a_group_wearing_the_pills_tray(rendered: str) -> None:
    tray = _nav_probe(rendered, "segmented")
    assert tray.startswith("<div ")
    assert 'role="group"' in tray
    assert "flex gap-0 bg-background p-1 rounded-lg mt-2" in tray
    assert "role=\"tablist\"" not in tray


def test_segment_states_hang_off_data_active(rendered: str) -> None:
    seg = _nav_probe(rendered, "segment")
    assert seg.startswith("<button ")
    assert 'data-active="false"' in seg
    assert ':data-active="chart === \'timeline\'"' in seg
    assert "@click=\"pick('timeline')\"" in seg
    assert "data-[active=true]:text-primary data-[active=true]:bg-surface" in seg
    assert "data-[active=true]:hover:bg-surface" in seg
    assert "data-[active=true]:shadow-[var(--shadow-xs)]" in seg


def test_segment_resting_ink_is_not_the_important_utility(rendered: str) -> None:
    seg = _nav_probe(rendered, "segment")
    # text-text-muted is !important in tailwind.src.css and would outrank the
    # chosen segment's colour, so the resting ink is the arbitrary form.
    assert "text-[color:var(--color-text-muted)]" in seg
    assert " text-text-muted" not in seg


def test_segment_states_its_line_height_and_the_pill_shape(rendered: str) -> None:
    seg = _nav_probe(rendered, "segment")
    assert "px-5 py-3.5 text-sm leading-[1.5] font-medium rounded-md" in seg
    assert "border-b" not in seg


def test_segment_is_never_taken_out_of_the_tab_order(rendered: str) -> None:
    seg = _nav_probe(rendered, "segment")
    assert "tabindex" not in seg
    assert "aria-selected" not in seg
