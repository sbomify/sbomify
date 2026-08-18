"""Render contract for the cotton tables component set.

The probe template composes a whole data table out of components/tables; these
tests pin the parts each component emits, the recipes their props switch and
the Alpine state names the sortable header and the pager rely on, so a page can
nest the set without ever writing a class itself.
"""

import pytest
from django.template.loader import render_to_string


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string("core/cotton_probes/tables.html.j2")


def _element_holding(rendered: str, tag: str, marker: str) -> str:
    """The first `tag` element holding `marker`, bounded by the element that follows it."""
    chunks = [part for part in rendered.split(f"<{tag}") if marker in part]
    assert chunks, f"no <{tag}> holds {marker!r}"
    element = chunks[0].split(f"</{tag}>")[0]
    assert marker in element, f"{marker!r} is not inside a <{tag}>"
    return element


def test_shell_frames_the_table(rendered: str) -> None:
    shell = _element_holding(rendered, "div", 'data-probe="shell"')
    for bit in ("flex flex-col overflow-hidden", "bg-surface", "border border-solid border-border", "rounded-xl"):
        assert bit in shell
    assert "mb-8" in shell


def test_nested_shell_drops_its_own_frame(rendered: str) -> None:
    nested = _element_holding(rendered, "div", "bg-transparent")
    assert "flex flex-col overflow-hidden" in nested
    assert "border-border" not in nested
    assert "rounded-xl" not in nested


def test_toolbar_recipe(rendered: str) -> None:
    # px-4 py-4, never p-4: the public base's pre-Tailwind utilities.css carries
    # an !important .p-4 that would repad the band there.
    band = [part for part in rendered.split("<div") if "justify-between gap-4 px-4 py-4" in part][0]
    assert "flex flex-wrap items-center" in band
    assert " p-4 " not in band
    assert "bg-[color-mix(in_oklab,var(--color-background)_50%,transparent)]" in band
    assert "border-b border-solid border-[color-mix(in_oklab,var(--color-border)_50%,transparent)]" in band


def test_toolbar_renders_the_right_group_only_when_it_is_filled(rendered: str) -> None:
    filled, without_right = rendered.split("bg-transparent", 1)
    assert filled.count('<div class="flex items-center gap-3">') == 2
    assert without_right.count('<div class="flex items-center gap-3">') == 1


def test_search_field_recipe_and_label_pairing(rendered: str) -> None:
    field = _element_holding(rendered, "input", 'id="probe-search"')
    for bit in ("py-2 pr-3 pl-9", "min-w-[240px]", "bg-surface", "rounded-[0.5rem]", "placeholder:text-text-muted"):
        assert bit in field
    assert "focus:outline-none focus:border-primary" in field
    assert "focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-primary)_10%,transparent)]" in field
    assert 'placeholder="Search components"' in field
    assert '<label for="probe-search" class="sr-only">Search components</label>' in rendered
    assert '<i class="fas fa-search absolute left-3 text-sm text-text-muted pointer-events-none"' in rendered


def test_search_forwards_its_binding_to_the_input(rendered: str) -> None:
    assert 'x-model="search"' in _element_holding(rendered, "input", 'id="probe-search"')


def test_page_size_select_recipe_and_options_slot(rendered: str) -> None:
    select = _element_holding(rendered, "select", 'id="probe-per-page"')
    for bit in ("py-1.5 pr-8 pl-3", "appearance-none", "bg-[position:right_0.5rem_center]", "bg-[length:1.25rem]"):
        assert bit in select
    assert "bg-[url(data:image/svg+xml," in select
    assert 'x-model.number="perPage"' in select
    assert '<option value="10">Ten</option>' in select
    assert '<label for="probe-per-page" class="sr-only">Entries per page</label>' in rendered
    assert "<span>Show</span>" in rendered
    assert "<span>entries</span>" in rendered


def test_table_scrolls_inside_its_own_box(rendered: str) -> None:
    assert '<div class="overflow-x-auto">' in rendered
    assert "w-full border-separate border-spacing-0" in _element_holding(rendered, "table", 'data-probe="table"')


def test_fixed_table_centres_every_middle_column(rendered: str) -> None:
    fixed = _element_holding(rendered, "table", 'data-probe="table"')
    assert "table-fixed" in fixed
    assert "[&_th:not(:first-child):not(:last-child):not([data-cell-end])]:text-center" in fixed
    assert "[&_td:not(:first-child):not(:last-child):not([data-cell-end])]:text-center" in fixed
    assert "[&_td:not(:first-child):not(:last-child):not([data-cell-end])>.flex]:justify-center" in fixed


def test_sized_table_fixes_the_layout_without_imposing_alignment(rendered: str) -> None:
    """A table whose header cells state their own widths keeps its values left."""
    sized = _element_holding(rendered, "table", 'data-probe="table-sized"')
    assert "table-fixed" in sized
    assert "text-center" not in sized
    assert "justify-center" not in sized


def test_plain_table_stays_content_sized(rendered: str) -> None:
    plain = _element_holding(rendered, "table", "Unfixed body cell")
    assert "w-full border-separate border-spacing-0" in plain
    assert "table-fixed" not in plain


def test_head_renders_the_header_row(rendered: str) -> None:
    head = _element_holding(rendered, "thead", "Unsorted head")
    assert 'class="align-bottom"' in head
    assert "<tr>" in head


def test_header_cell_band_recipe(rendered: str) -> None:
    cell = _element_holding(rendered, "th", "Unsorted head")
    for bit in (
        "px-5 py-4",
        "text-[0.75rem] font-semibold uppercase tracking-[0.05em]",
        "text-text-muted bg-background",
        "border-b border-solid border-border",
        "sticky top-0 z-[1]",
        "first:rounded-tl-lg last:rounded-tr-lg",
        "first:pl-4 last:pr-4 max-sm:px-2",
    ):
        assert bit in cell


def test_header_cell_alignment_segments_never_conflict(rendered: str) -> None:
    left = _element_holding(rendered, "th", "Unsorted head")
    assert "text-left" in left
    assert "text-right" not in left
    assert "data-cell-end" not in left
    right = _element_holding(rendered, "th", "Visibility column")
    assert "text-right" in right
    assert "text-left" not in right
    assert "data-cell-end" in right


def test_header_cell_date_column_stays_on_one_line(rendered: str) -> None:
    dated = _element_holding(rendered, "th", "Created column")
    assert "whitespace-nowrap" in dated
    assert "hidden md:table-cell" in dated


def test_sortable_header_keeps_the_table_state_names(rendered: str) -> None:
    sortable = _element_holding(rendered, "th", "Name column")
    assert (
        ":aria-sort=\"sortColumn === 'name' ? (sortDirection === 'asc' ? 'ascending' : 'descending') : 'none'\""
        in sortable
    )
    assert ":data-sort=\"sortColumn === 'name' ? sortDirection : 'none'\"" in sortable
    assert "@click=\"sort('name')\"" in sortable
    assert 'data-sort="none"' in sortable
    assert "inline-flex items-center gap-2 uppercase cursor-pointer select-none hover:text-primary" in sortable
    assert "focus-visible:shadow-[0_0_0_2px_color-mix(in_oklab,var(--color-primary)_50%,transparent)]" in sortable


def test_sortable_header_label_is_uppercase_like_an_unsorted_one(rendered: str) -> None:
    """The th sets uppercase, but a button is a form control and the UA
    stylesheet gives it text-transform: none, so the label has to restate it.
    Without this a table renders "Name / STATUS / Last Modified", uppercase on
    exactly the columns that happen not to sort.
    """
    sortable = _element_holding(rendered, "th", "Name column")
    unsorted = _element_holding(rendered, "th", "Unsorted head")
    assert "uppercase" in unsorted
    assert "uppercase" in sortable.split("<button", 1)[1]


def test_sort_icon_states_are_mutually_exclusive(rendered: str) -> None:
    sortable = _element_holding(rendered, "th", "Name column")
    assert "flex flex-col gap-px opacity-30" in sortable
    assert "[[data-sort=none]:hover_&]:opacity-60" in sortable
    assert "[[data-sort=asc]_&]:opacity-100 [[data-sort=asc]_&]:text-primary" in sortable
    assert "[[data-sort=desc]_&]:opacity-100 [[data-sort=desc]_&]:text-primary" in sortable
    assert "fa-caret-up text-[0.5rem] leading-none [[data-sort=desc]_&]:opacity-25" in sortable
    assert "fa-caret-down text-[0.5rem] leading-none [[data-sort=asc]_&]:opacity-25" in sortable


def test_header_without_sort_has_no_control(rendered: str) -> None:
    assert "<button" not in _element_holding(rendered, "th", "Unsorted head")


def test_row_tints_on_hover_and_the_last_row_loses_its_rule(rendered: str) -> None:
    row = _element_holding(rendered, "tr", "Plain body cell")
    assert "transition-all duration-150" in row
    assert "hover:bg-[color-mix(in_oklab,var(--color-primary)_4%,transparent)]" in row
    assert "last:[&_td]:border-b-0" in row
    assert 'tabindex="0"' in row
    assert '@click="open()"' in row


def test_body_cell_recipe(rendered: str) -> None:
    cell = _element_holding(rendered, "td", "Plain body cell")
    for bit in (
        "px-5 py-5 text-[0.875rem] text-text",
        "border-b border-solid border-[color-mix(in_oklab,var(--color-border)_50%,transparent)]",
        "transition-[background-color] duration-150",
        "first:pl-4 last:pr-4 max-sm:px-2",
        "font-medium",
    ):
        assert bit in cell
    assert "text-right" not in cell
    assert "whitespace-nowrap" not in cell


def test_cell_muted_replaces_the_ink_rather_than_stacking_on_it(rendered: str) -> None:
    """Two colours would be settled by stylesheet order, so the ink is one segment."""
    muted = _element_holding(rendered, "td", "Muted cell")
    assert "px-5 py-5 text-[0.875rem] text-text-muted border-b" in muted
    plain = _element_holding(rendered, "td", "Plain body cell")
    assert "text-text-muted" not in plain


def test_cell_end_and_date_segments(rendered: str) -> None:
    dated = _element_holding(rendered, "td", "10 Aug 2026")
    assert "whitespace-nowrap" in dated
    assert "text-right" not in dated
    end = _element_holding(rendered, "td", "Right cell")
    assert "text-right" in end
    assert "data-cell-end" in end
    assert 'hx-get="/probe"' in end


def test_actions_header_cell_names_the_column_for_screen_readers(rendered: str) -> None:
    header = _element_holding(rendered, "th", "Row actions")
    assert '<span class="sr-only">Row actions</span>' in header
    assert "sticky top-0 z-[1]" in header
    assert "text-right whitespace-nowrap" in header
    assert "data-cell-end" in header


def test_actions_cell_states_its_own_column_gutters(rendered: str) -> None:
    body = _element_holding(rendered, "td", "Component actions")
    assert "w-22 last:pr-4 max-sm:w-16 max-sm:pl-1 max-sm:pr-2" in body
    assert "max-sm:px-2" not in body
    assert "px-5 py-5 text-[0.875rem] text-text" in body
    header = _element_holding(rendered, "th", "Row actions")
    assert "w-22 last:pr-4 max-sm:w-16 max-sm:pl-1 max-sm:pr-2" in header
    assert "max-sm:px-2" not in header


def test_actions_cell_forwards_attrs_and_nests_its_menu_button(rendered: str) -> None:
    body = _element_holding(rendered, "td", "Component actions")
    assert "@click.stop" in body
    assert 'aria-label="Component actions"' in body
    assert "<button" in body


def test_footer_recipe(rendered: str) -> None:
    footer = [part for part in rendered.split("<div") if "px-4 py-3.5" in part][0]
    assert "flex flex-wrap items-center justify-between gap-4" in footer
    assert "bg-[color-mix(in_oklab,var(--color-background)_50%,transparent)]" in footer
    assert "border-t border-solid border-[color-mix(in_oklab,var(--color-border)_50%,transparent)]" in footer


def test_info_line_brings_its_numbers_forward(rendered: str) -> None:
    info = _element_holding(rendered, "div", "text-[0.8125rem]")
    assert "text-text-muted" in info
    assert "[&_strong]:font-semibold [&_strong]:text-text" in info
    assert "Showing <strong>1</strong> to <strong>2</strong> of <strong>2</strong> entries" in rendered


def test_pager_drives_the_current_page_state(rendered: str) -> None:
    pager = [part for part in rendered.split('<div class="flex items-center gap-2"') if "Previous page" in part][0]
    assert 'aria-label="Previous page"' in pager
    assert ':disabled="currentPage === 1"' in pager
    assert '@click="if (currentPage > 1) currentPage--"' in pager
    assert 'aria-label="Next page"' in pager
    assert ':disabled="currentPage === totalPages"' in pager
    assert '@click="if (currentPage < totalPages) currentPage++"' in pager
    assert '<span x-text="currentPage"></span> / <span x-text="totalPages"></span>' in pager


def test_pager_arrows_render_through_the_buttons_set(rendered: str) -> None:
    pager = [part for part in rendered.split('<div class="flex items-center gap-2"') if "Previous page" in part][0]
    assert "px-3.5 py-2 min-h-9 text-xs rounded-md" in pager
    assert "bg-surface text-text border border-solid border-border" in pager
    assert '<i class="fas fa-chevron-left text-xs" aria-hidden="true"></i>' in pager
