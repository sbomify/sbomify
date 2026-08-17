"""Render contract for the cotton forms component set.

The probe template exercises every component in components/forms; these tests
pin the recipes each control emits, the segments its props select, and the way
a field composes a label, a control and one line of help, so pages can rely on
the components without ever writing a class themselves.
"""

import pytest
from django.template.loader import render_to_string

CONTROL_SHELL = "w-full px-4 py-3 bg-surface border-[1.5px] border-solid rounded-lg text-text text-sm"
PRIMARY_RING = "focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-primary)_15%,transparent)]"
INPUT_PRIMARY_RING = PRIMARY_RING.removesuffix("]") + ",var(--shadow-xs)]"
DANGER_RING = "focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-danger)_15%,transparent)]"
SUCCESS_RING = "focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-success)_15%,transparent)]"
CHEVRON = "bg-[url('data:image/svg+xml,%3csvg%20xmlns=%22http://www.w3.org/2000/svg%22"
TICK = "checked:bg-[url('data:image/svg+xml,%3csvg%20viewBox=%220%200%2016%2016%22%20fill=%22white%22"
DASH = "indeterminate:bg-[url('data:image/svg+xml,%3csvg%20viewBox=%220%200%2016%2016%22%20fill=%22none%22"
REST_ZONE = "border-dashed border-border bg-background"
ACTIVE_ZONE = "border-solid border-primary bg-[color-mix(in_oklab,var(--color-primary)_8%,transparent)]"


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string(
        "core/cotton_probes/forms.html.j2",
        {"probe_options": [{"value": "sbom", "label": "SBOM"}, {"value": "document", "label": "Document"}]},
    )


def _chunk(rendered: str, tag: str, marker: str) -> str:
    """The markup of the `tag` element that holds `marker`, closing tag included."""
    chunks = [part for part in rendered.split(f"<{tag}") if marker in part]
    assert chunks, f"no <{tag}> holds {marker!r}"
    chunk = chunks[0]
    end = chunk.find(f"</{tag}>")
    return chunk if end == -1 else chunk[: end + len(tag) + 3]


def _open_tag(rendered: str, tag: str, marker: str) -> str:
    """Just the opening tag: attributes only, nothing the element wraps."""
    chunk = _chunk(rendered, tag, marker)
    return chunk[: chunk.index(">") + 1]


def _classes(rendered: str, tag: str, marker: str) -> set[str]:
    """The element's own class list, as whole utilities.

    Substring checks lie here: border-border is inside border-border-light, and
    a segment test has to prove a utility is absent, not merely spelled
    differently.
    """
    open_tag = _open_tag(rendered, tag, marker)
    start = open_tag.index('class="') + len('class="')
    return set(open_tag[start : open_tag.index('"', start)].split())


# ── Label, hint and error ───────────────────────────────────────────────────


def test_label_recipe_and_required_marker(rendered: str) -> None:
    label = _chunk(rendered, "label", "Standalone label")
    assert "block text-sm leading-[1.5] font-medium text-text mb-2 tracking-[-0.01em]" in label
    assert 'for="probe-standalone"' in label
    assert '<span class="text-danger">*</span>' in label


def test_label_without_for_or_required_renders_neither(rendered: str) -> None:
    label = _chunk(rendered, "label", "Bare label")
    assert "for=" not in label.split(">")[0]
    assert "text-danger" not in label
    assert "mb-0" in label


def test_hint_and_error_recipes(rendered: str) -> None:
    assert "block text-xs leading-[1.5] text-text-muted mt-1.5" in _chunk(rendered, "p", "Standalone hint")
    assert "flex items-center gap-1 text-xs leading-[1.5] text-danger mt-1.5" in _chunk(
        rendered, "p", "Standalone error"
    )


def test_error_slot_carries_nested_markup(rendered: str) -> None:
    assert '<i class="fas fa-circle-exclamation" aria-hidden="true"></i> <span>Standalone error</span>' in rendered


# ── Field composition ───────────────────────────────────────────────────────


def test_field_stacks_label_then_control_then_hint(rendered: str) -> None:
    field = _chunk(rendered, "div", 'data-probe="field"')
    assert "space-y-1.5" in field
    assert field.index("Text</label>".replace("</label>", "")) < field.index('id="probe-text"')
    assert field.index('id="probe-text"') < field.index("Shown under the field.")


def test_field_error_replaces_the_hint(rendered: str) -> None:
    field = _chunk(rendered, "div", 'for="probe-ok"')
    assert "Both were given." in field
    assert "Never seen: the error wins." not in field


def test_field_class_is_layout_and_does_not_reach_its_parts(rendered: str) -> None:
    assert "md:col-span-2" in _open_tag(rendered, "div", 'data-probe="field"')
    assert "md:col-span-2" not in _chunk(rendered, "label", 'for="probe-text"')
    assert "md:col-span-2" not in _chunk(rendered, "p", "Shown under the field.")


def test_field_without_a_for_labels_the_group_and_holds_several_controls(rendered: str) -> None:
    field = _chunk(rendered, "div", "A group has no single control to point at.")
    label = _chunk(rendered, "label", "Format")
    assert "for=" not in label.split(">")[0]
    assert field.count('name="probe-format"') == 2


def test_field_passes_required_to_its_label(rendered: str) -> None:
    assert '<span class="text-danger">*</span>' in _chunk(rendered, "label", 'for="probe-error"')
    assert "text-danger" not in _chunk(rendered, "label", 'for="probe-text"')


# ── Input ───────────────────────────────────────────────────────────────────


def test_input_shell_and_default_state_segment(rendered: str) -> None:
    field = _open_tag(rendered, "input", 'id="probe-text"')
    assert CONTROL_SHELL in field
    assert "border-border" in field
    assert INPUT_PRIMARY_RING in field
    assert 'type="text"' in field
    assert 'name="probe-text"' in field
    assert 'placeholder="Acme Gateway"' in field


def test_input_error_state_segment_and_non_conflict(rendered: str) -> None:
    field = _open_tag(rendered, "input", 'id="probe-error"')
    classes = _classes(rendered, "input", 'id="probe-error"')
    assert "border-danger" in classes
    assert DANGER_RING in field
    assert "border-border" not in classes
    assert INPUT_PRIMARY_RING not in field
    assert 'type="email"' in field
    assert 'value="not-an-email"' in field


def test_input_success_state_segment_and_non_conflict(rendered: str) -> None:
    field = _open_tag(rendered, "input", 'id="probe-ok"')
    classes = _classes(rendered, "input", 'id="probe-ok"')
    assert "border-success" in classes
    assert SUCCESS_RING in field
    assert "border-border" not in classes


def test_input_hover_and_disabled_utilities_are_shared(rendered: str) -> None:
    field = _open_tag(rendered, "input", 'id="probe-text"')
    assert "hover:not-focus:not-disabled:border-border-light" in field
    assert "disabled:opacity-60 disabled:cursor-not-allowed disabled:bg-background" in field


def test_input_boolean_props_render_bare_attributes(rendered: str) -> None:
    locked = _open_tag(rendered, "input", 'id="probe-locked"')
    assert "disabled" in locked
    assert "readonly" in locked
    assert '="False"' not in locked
    assert "required" in _open_tag(rendered, "input", 'id="probe-error"')
    assert "required" not in _open_tag(rendered, "input", 'id="probe-text"')


def test_input_attrs_and_class_pass_through(rendered: str) -> None:
    field = _open_tag(rendered, "input", 'id="probe-text"')
    assert 'hx-get="/probe"' in field
    assert '@keydown.enter="go()"' in field
    assert "font-mono" in field


# ── Select ──────────────────────────────────────────────────────────────────


def test_select_default_segments_and_chevron(rendered: str) -> None:
    select = _open_tag(rendered, "select", 'id="probe-select"')
    assert "appearance-none cursor-pointer" in select
    assert CHEVRON in select
    assert "bg-no-repeat bg-[position:right_0.75rem_center] bg-[length:1.25rem]" in select
    assert "w-full py-3 pr-10 pl-4 text-sm" in select
    assert "bg-surface border-border text-text" in select
    assert PRIMARY_RING in select


def test_select_small_segment_never_conflicts_with_the_default(rendered: str) -> None:
    select = _open_tag(rendered, "select", 'id="probe-select-sm"')
    classes = _classes(rendered, "select", 'id="probe-select-sm"')
    assert "w-auto py-1 pr-7 pl-2 text-xs" in select
    for bit in ("w-full", "py-3", "pr-10", "pl-4", "text-sm"):
        assert bit not in classes


@pytest.mark.parametrize("accent", ["success", "warning", "danger"])
def test_select_accent_tints_border_fill_and_ink_together(rendered: str, accent: str) -> None:
    select = _open_tag(rendered, "select", f'id="probe-select-{accent}"')
    classes = _classes(rendered, "select", f'id="probe-select-{accent}"')
    assert f"bg-[color-mix(in_oklab,var(--color-{accent})_10%,transparent)]" in classes
    assert f"border-[color-mix(in_oklab,var(--color-{accent})_30%,transparent)]" in classes
    assert f"text-{accent}" in classes
    assert "bg-surface" not in classes
    assert "border-border" not in classes
    assert "text-text" not in classes
    assert PRIMARY_RING in select


def test_select_state_outranks_accent(rendered: str) -> None:
    select = _open_tag(rendered, "select", 'id="probe-select-error"')
    classes = _classes(rendered, "select", 'id="probe-select-error"')
    assert "bg-surface border-danger text-text" in select
    assert DANGER_RING in select
    assert "bg-[color-mix(in_oklab,var(--color-danger)_10%,transparent)]" not in classes


def test_select_options_come_from_the_prop_and_mark_the_selection(rendered: str) -> None:
    select = _chunk(rendered, "select", 'id="probe-select"')
    assert 'value=""' in select
    assert "Choose one" in select
    assert "selected" in select[select.index('value="document"') : select.index("Document</option>")]
    assert "selected" not in select[select.index('value="sbom"') : select.index("SBOM</option>")]


def test_select_slot_renders_hand_written_options(rendered: str) -> None:
    select = _chunk(rendered, "select", 'id="probe-select-slot"')
    assert '<option value="from-slot">From the slot</option>' in select
    assert 'x-model="kind"' in select


# ── Textarea ────────────────────────────────────────────────────────────────


def test_textarea_recipe_rows_and_value(rendered: str) -> None:
    area = _chunk(rendered, "textarea", 'id="probe-textarea"')
    assert "w-full min-h-28 px-4 py-3 bg-surface border-[1.5px] border-solid rounded-lg" in area
    assert "leading-normal resize-y" in area
    assert 'rows="3"' in area
    assert ">Existing copy</textarea>" in area
    assert "border-border" in area
    assert PRIMARY_RING in area


def test_textarea_error_state_segment_and_non_conflict(rendered: str) -> None:
    area = _open_tag(rendered, "textarea", 'id="probe-textarea-error"')
    classes = _classes(rendered, "textarea", 'id="probe-textarea-error"')
    assert "border-danger" in classes
    assert DANGER_RING in area
    assert "border-border" not in classes
    assert 'rows="4"' in area


# ── Checkbox, radio and toggle ──────────────────────────────────────────────


def test_checkbox_draws_every_state_on_the_real_input(rendered: str) -> None:
    box = _open_tag(rendered, "input", 'id="probe-check"')
    assert "w-5 h-5 shrink-0 relative appearance-none" in box
    assert "checked:bg-primary checked:border-primary" in box
    assert TICK in box
    assert DASH in box
    assert "focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-primary)_25%,transparent)]" in box
    assert "disabled:opacity-50 disabled:cursor-not-allowed" in box
    assert "checked" in box
    assert '@change="save()"' in box


def test_checkbox_touch_target_is_an_invisible_pseudo_element(rendered: str) -> None:
    box = _open_tag(rendered, "input", 'id="probe-check"')
    assert "after:content-[''] after:absolute after:top-1/2 after:left-1/2" in box
    assert "after:w-11 after:h-11 after:rounded-lg" in box


def test_checkbox_label_wraps_the_input_and_takes_the_class(rendered: str) -> None:
    label = _chunk(rendered, "label", 'id="probe-check-disabled"')
    assert 'class="flex items-center gap-3 w-full"' in label
    assert '<span class="text-sm text-text">Checkbox disabled</span>' in label
    assert "disabled" in label


def test_checkbox_without_a_slot_renders_no_text(rendered: str) -> None:
    label = _chunk(rendered, "label", 'id="probe-check-bare"')
    assert "text-sm text-text" not in label
    assert 'aria-label="Select all"' in label
    assert 'x-ref="all"' in label


def test_bare_checkbox_input_is_the_same_control_without_a_label(rendered: str) -> None:
    box = _open_tag(rendered, "input", 'id="probe-check-input"')
    labelled = _open_tag(rendered, "input", 'id="probe-check"')
    recipe = "w-5 h-5 shrink-0 relative appearance-none"
    assert recipe in box
    assert recipe in labelled
    assert TICK in box
    assert DASH in box
    # The row around it is the control, so the box takes no pointer of its own
    # and the caller's class lands on the input rather than on a label.
    assert "pointer-events-none" in box
    assert 'tabindex="-1"' in box
    assert ':checked="isSelected(row.id)"' in box


def test_bare_checkbox_input_has_no_label_around_it(rendered: str) -> None:
    at = rendered.index('id="probe-check-input"')
    opening = rendered.rindex("<", 0, at)
    assert not rendered[:opening].rstrip().endswith("<label")


def test_radio_marks_selection_by_thickening_its_own_border(rendered: str) -> None:
    radio = _open_tag(rendered, "input", 'value="cyclonedx"')
    assert "rounded-full" in radio
    assert "after:w-11 after:h-11 after:rounded-full" in radio
    assert "checked:bg-white checked:border-primary checked:border-[5px]" in radio
    assert "checked" in radio
    assert "id=" not in radio


def test_radio_group_shares_a_name(rendered: str) -> None:
    assert _open_tag(rendered, "input", 'value="spdx"').count('name="probe-radio"') == 1
    assert "disabled" in _open_tag(rendered, "input", 'value="spdx"')


def test_bound_radio_value_replaces_the_static_attribute(rendered: str) -> None:
    """Alpine only writes a bound value onto a radio with no value attribute."""
    radio = _open_tag(rendered, "input", 'data-probe="radio-bound"')
    assert ':value="proc.value"' in radio
    assert 'value=""' not in radio
    assert 'x-model="procedure"' in radio


def test_toggle_track_and_knob_are_the_input_and_its_pseudo_element(rendered: str) -> None:
    toggle = _open_tag(rendered, "input", 'id="probe-toggle"')
    assert "relative w-12 h-6.5 shrink-0 appearance-none cursor-pointer bg-border rounded-full" in toggle
    assert "before:content-[''] before:absolute before:top-0.75 before:left-0.75 before:w-5 before:h-5" in toggle
    assert "checked:bg-[linear-gradient(135deg,var(--color-primary)_0%,var(--color-primary-dark)_100%)]" in toggle
    assert "checked:before:translate-x-[1.375rem]" in toggle
    assert '@change="publish()"' in toggle


def test_toggle_label_dims_from_the_input_state(rendered: str) -> None:
    label = _chunk(rendered, "label", 'id="probe-toggle-disabled"')
    assert "has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60" in label
    assert "disabled" in label


# ── Search input ────────────────────────────────────────────────────────────


def test_search_input_precedes_the_icon_so_peer_can_reach_it(rendered: str) -> None:
    field = _chunk(rendered, "div", 'placeholder="Search products, components…"')
    assert field.index('type="search"') < field.index("fa-search")
    assert "peer w-full py-3 pl-11 pr-4" in field
    # The old rule set only a font-size and inherited 1.5, so the field states it.
    assert "text-sm leading-[1.5]" in field
    assert "peer-focus:text-primary" in field
    assert "pointer-events-none" in field


def test_search_hint_segment_reserves_the_shortcut_room(rendered: str) -> None:
    field = _open_tag(rendered, "input", 'id="probe-search-hint"')
    assert "pl-11 pr-14" in field
    assert "pr-4" not in field


def test_search_clear_button_is_wired_to_the_model(rendered: str) -> None:
    button = _chunk(rendered, "button", 'aria-label="Clear search"')
    assert "opacity-0 transition-all duration-150 peer-[:not(:placeholder-shown)]:opacity-100" in button
    assert 'x-show="q"' in button
    assert "@click=\"q = ''\"" in button


def test_search_without_a_model_has_no_clear_button(rendered: str) -> None:
    field = _chunk(rendered, "div", 'id="probe-search-hint"')
    assert "Clear search" not in field
    assert "x-model" not in field
    assert 'autocomplete="off"' in field
    assert "fa-magnifying-glass" in field
    assert "<kbd" in field


# ── File upload ─────────────────────────────────────────────────────────────


def test_file_upload_active_swaps_the_whole_recipe_rather_than_adding_to_it(rendered: str) -> None:
    panel = _open_tag(rendered, "label", "@dragover.prevent")
    classes = _classes(rendered, "label", "@dragover.prevent")
    assert f":class=\"over ? '{ACTIVE_ZONE}' : '{REST_ZONE}'\"" in panel
    assert "group flex flex-col items-center justify-center px-8 py-10 border-2 rounded-xl" in panel
    # Nothing static may fight the binding: border style, border colour and fill
    # come from whichever branch is live, never from two utilities at once.
    for utility in ("border-dashed", "border-solid", "border-border", "border-primary", "bg-background"):
        assert utility not in classes


def test_file_upload_without_active_carries_the_resting_recipe(rendered: str) -> None:
    panel = _open_tag(rendered, "label", 'id="probe-upload-plain"')
    assert REST_ZONE in panel
    assert ":class" not in panel


def test_file_upload_keeps_the_drop_handlers_on_the_panel(rendered: str) -> None:
    panel = _open_tag(rendered, "label", "@dragover.prevent")
    assert '@dragover.prevent="over = true"' in panel
    assert '@dragleave.prevent="over = false"' in panel
    assert '@drop.prevent="over = false"' in panel


def test_file_upload_icon_grows_with_the_panel(rendered: str) -> None:
    panel = _chunk(rendered, "label", 'id="probe-upload"')
    # The medallion is the span, not the mark: Font Awesome's unlayered
    # display:inline-block outranks a flex utility on the same element, and the
    # circle collapsed to a pill. The glyph is 1.5rem inside a 4rem circle.
    assert '<span class="w-16 h-16 flex items-center justify-center rounded-full' in panel
    assert '<i class="fas fa-cloud-arrow-up text-2xl"' in panel
    assert "group-hover:scale-110" in panel
    assert (
        "bg-[linear-gradient(135deg,color-mix(in_oklab,var(--color-primary)_15%,transparent)_0%,"
        "color-mix(in_oklab,var(--color-primary)_5%,transparent)_100%)]"
    ) in panel


def test_file_upload_text_hint_and_hidden_input(rendered: str) -> None:
    panel = _chunk(rendered, "label", 'id="probe-upload"')
    assert '<span class="text-[0.9375rem] font-medium text-text text-center">Drop an SBOM here' in panel
    assert '<span class="text-[0.8125rem] text-text-muted mt-2">CycloneDX or SPDX, JSON or XML</span>' in panel
    assert 'type="file"' in panel
    assert 'class="sr-only"' in panel
    assert 'accept=".json,.xml"' in panel
    assert '@change="pick($event)"' in panel


def test_file_upload_static_is_the_panel_without_the_picker(rendered: str) -> None:
    """The upload-in-flight state keeps the zone's shape and drops the input."""
    panel = _chunk(rendered, "div", 'data-probe="upload-static"')
    assert "group flex flex-col items-center justify-center px-8 py-10 border-2 rounded-xl" in panel
    assert REST_ZONE in panel
    # Nothing to pick, so nothing to click or type into.
    assert "cursor-pointer" not in panel
    assert 'type="file"' not in panel
    # The slot is the whole content: no main line, no hint, no mark.
    assert "text-[0.9375rem] font-medium text-text text-center" not in panel
    assert "Uploading and processing document..." in panel


def _preview(rendered: str) -> str:
    """The whole preview row. _chunk stops at the first closing div, which is
    the row's own text column, so the row is sliced up to the probe after it."""
    start = rendered.index('data-probe="file-preview"')
    return rendered[start : rendered.index("probe-bound-state", start)]


def test_file_preview_carries_its_own_row(rendered: str) -> None:
    row = _chunk(rendered, "div", 'data-probe="file-preview"')
    assert "flex items-center gap-3 mt-4 px-4 py-3 bg-surface border border-solid border-border rounded-lg" in row
    assert "w-10 h-10 rounded-md bg-[color-mix(in_oklab,var(--color-primary)_10%,transparent)] text-primary" in row


def test_file_preview_name_clips_and_size_stays_quiet(rendered: str) -> None:
    row = _preview(rendered)
    assert '<p class="text-[0.875rem] font-medium text-text truncate m-0"><span x-text="picked.name">' in row
    assert '<p class="text-[0.75rem] text-text-muted m-0"><span x-text="formatFileSize(picked.size)">' in row
    # The lines state a size and inherit their line-height, as a table cell does.
    assert "text-sm" not in row
    assert "text-xs" not in row


def test_file_preview_action_slot_holds_a_real_button(rendered: str) -> None:
    row = _preview(rendered)
    assert 'aria-label="Remove selected file"' in row
    assert '@click="clearSelectedFile()"' in row


def test_input_carries_the_runtime_state_recipes(rendered: str) -> None:
    """An editor whose validity is client state binds data-state, never a class."""
    field = _open_tag(rendered, "input", 'name="probe-bound-state"')
    assert ":data-state=\"formErrors.name ? 'error' : ''\"" in field
    assert "data-[state=error]:border-danger" in field
    assert (
        "data-[state=error]:focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-danger)_15%,transparent)]" in field
    )
    assert "data-[state=success]:border-success" in field
    # The resting recipe is still the fallback, so an empty state renders plain.
    assert "border-border" in field


def test_textarea_carries_the_runtime_state_recipes(rendered: str) -> None:
    field = _open_tag(rendered, "textarea", 'name="probe-bound-textarea"')
    assert "data-[state=error]:border-danger" in field
    assert "data-[state=success]:border-success" in field


# ── Colour field ────────────────────────────────────────────────────────────


def _colour(rendered: str) -> str:
    """The whole colour field, from its label through to the hidden input."""
    start = rendered.index('for="probe-colour"')
    return rendered[start : rendered.index("probe-colour-bare", start)]


def test_colour_field_wears_the_field_label_and_hint(rendered: str) -> None:
    """A colour reads as one of the form's fields, not a block beside them."""
    field = _colour(rendered)
    assert "Primary brand color" in field
    assert "Headers, navigation, primary elements" in field


def test_colour_field_draws_one_border_around_both_halves(rendered: str) -> None:
    """The swatch and the hex are one control, so the wrapper owns the ring."""
    wrapper = _open_tag(rendered, "div", "focus-within:border-primary")
    assert "border-[1.5px] border-solid border-border" in wrapper
    assert (
        "focus-within:shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-primary)_15%,transparent),var(--shadow-xs)]"
        in wrapper
    )
    # Neither input paints a border of its own.
    assert "border" not in _classes(rendered, "input", 'id="probe-colour"')


def test_colour_field_binds_both_halves_to_one_value(rendered: str) -> None:
    """Typing a hex drives the swatch and picking drives the hex."""
    swatch = _open_tag(rendered, "input", 'id="probe-colour-swatch"')
    hexed = _open_tag(rendered, "input", 'id="probe-colour"')
    for half in (swatch, hexed):
        assert ':value="branding.primary"' in half
        assert '@input="branding.primary = $event.target.value"' in half
    assert 'type="color"' in swatch
    assert 'type="text"' in hexed


def test_colour_field_names_the_picker_for_a_screen_reader(rendered: str) -> None:
    swatch = _open_tag(rendered, "input", 'id="probe-colour-swatch"')
    assert 'aria-label="Primary brand color, colour picker"' in swatch


def test_colour_field_posts_through_a_hidden_input_only_when_named(rendered: str) -> None:
    """The visible halves are display; a form gets one value, once."""
    field = _colour(rendered)
    assert '<input type="hidden" name="probe-colour" :value="branding.primary">' in field
    assert 'type="hidden"' not in rendered[rendered.index("probe-colour-bare") :]
