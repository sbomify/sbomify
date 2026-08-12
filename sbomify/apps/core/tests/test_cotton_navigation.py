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
    assert '<span class="text-text font-medium">Releases</span>' in crumbs


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


def test_panel_collapses_on_the_same_expression(rendered: str) -> None:
    panel = _chunk(rendered, "div", "Policies, roles and supplier relationships.")
    assert "px-6 pb-5 text-sm leading-[1.6] text-text-muted" in panel
    assert 'x-show="open === &#x27;org&#x27;" x-collapse' in panel


def test_a_section_without_a_state_stays_open(rendered: str) -> None:
    panel = _chunk(rendered, "div", "Always open without a state.")
    assert "x-show" not in panel
    assert ":aria-expanded" not in _chunk(rendered, "button", "Compact section")


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
