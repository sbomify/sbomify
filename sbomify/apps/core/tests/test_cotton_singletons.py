"""Render contract for the cotton singletons: the top-level components.

The probe template exercises every component that sits at the root of
components/ (modal, avatar, progress, code block, token display, copy button,
actions menu); these tests pin the shells, the segments that must never stack
and the components each one nests, so pages can rely on them without ever
writing a class themselves.
"""

import pytest
from django.template.loader import render_to_string


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string("core/cotton_probes/singletons.html.j2")


def _tag_around(rendered: str, needle: str) -> str:
    """The opening tag that carries (or immediately precedes) `needle`."""
    index = rendered.index(needle)
    return rendered[rendered.rindex("<", 0, index) : rendered.index(">", index)]


def _probe(rendered: str, name: str) -> str:
    return _tag_around(rendered, f'data-probe="{name}"')


def _section(rendered: str, name: str) -> str:
    """Everything this probe rendered, up to the next probe."""
    start = rendered.index(f'data-probe="{name}"')
    rest = rendered[start + 1 :]
    end = rest.find("data-probe=")
    return rest if end == -1 else rest[:end]


# --- modal ----------------------------------------------------------------


def test_modal_teleports_to_the_body_and_declares_its_dialog_role(rendered: str) -> None:
    section = _section(rendered, "modal-default")
    assert '<template x-teleport="body">' in rendered[: rendered.index('data-probe="modal-default"')]
    root = _probe(rendered, "modal-default")
    assert 'role="dialog"' in root
    assert 'aria-modal="true"' in root
    assert 'aria-labelledby="ds-modal-title"' in root
    assert 'id="ds-modal-title"' in section


def test_modal_panel_recipe_and_default_size(rendered: str) -> None:
    section = _section(rendered, "modal-default")
    assert "flex flex-col w-full" in section
    assert "max-h-[90vh] overflow-hidden bg-surface border border-solid border-border rounded-2xl" in section
    assert "shadow-[0_25px_50px_-12px_rgb(0_0_0/0.4)]" in section
    assert "max-w-lg" in section


def test_modal_form_child_joins_the_panels_flex_column(rendered: str) -> None:
    section = _section(rendered, "modal-default")
    for bit in ("[&>form]:flex", "[&>form]:flex-col", "[&>form]:flex-auto", "[&>form]:min-h-0"):
        assert bit in section


def test_modal_size_segments_never_stack(rendered: str) -> None:
    large = _section(rendered, "modal-lg")
    assert "max-w-3xl" in large
    assert "max-w-lg" not in large
    small = _section(rendered, "modal-sm")
    assert "max-w-sm" in small
    assert "max-w-lg" not in small


def test_modal_show_prop_drives_every_alpine_hook(rendered: str) -> None:
    root = _probe(rendered, "modal-lg")
    assert 'x-show="showPanel"' in root
    assert '@keydown.escape="showPanel = false"' in root
    large = _section(rendered, "modal-lg")
    dialog = large[: large.index("</template>")]
    assert 'x-trap.noscroll="showPanel"' in dialog
    assert '@click="showPanel = false"' in dialog
    assert "open = false" not in dialog


def test_modal_any_outside_click_closes(rendered: str) -> None:
    section = _section(rendered, "modal-default")
    # The backdrop dismisses, and so does the centering wrapper above it: .self
    # keeps a click inside the panel from counting as outside.
    assert '@click="open = false"' in section
    assert '@click.self="open = false"' in section
    assert "@click.stop" not in section


def test_close_prop_replaces_the_show_assignment_everywhere(rendered: str) -> None:
    root = _probe(rendered, "modal-close")
    assert '@keydown.escape="removeTarget = null"' in root
    section = _section(rendered, "modal-close")
    dialog = section[: section.index("</template>")]
    # Backdrop and close button run the same expression as escape does.
    assert dialog.count('@click="removeTarget = null"') == 2
    assert "removeTarget = false" not in dialog
    # The open state itself is untouched: it still only reads.
    assert 'x-show="removeTarget"' in root


def test_modal_header_icon_is_the_library_chip_at_its_own_size(rendered: str) -> None:
    large = _section(rendered, "modal-lg")
    assert "var(--chip-accent,var(--color-primary))_12%" in large
    # The dialog's own size prop must not reach the chip.
    assert "w-10 h-10 rounded-lg" in large
    assert "w-12 h-12 text-lg" not in large


def test_modal_close_button_is_optional_and_labelled(rendered: str) -> None:
    assert 'aria-label="Close"' in _section(rendered, "modal-default")
    assert 'aria-label="Close"' not in _section(rendered, "modal-sm")


def test_modal_role_is_a_prop_so_a_confirmation_can_interrupt(rendered: str) -> None:
    """A second role in attrs would be a duplicate attribute the browser drops."""
    root = _probe(rendered, "modal-alert")
    assert 'role="alertdialog"' in root
    assert 'role="dialog"' not in root


def test_modal_without_a_title_renders_no_header(rendered: str) -> None:
    small = _section(rendered, "modal-sm")
    assert "border-b border-solid" not in small
    assert "aria-labelledby" not in _probe(rendered, "modal-sm")


def test_modal_slots_land_in_body_and_footer(rendered: str) -> None:
    default = _section(rendered, "modal-default")
    assert "flex-auto min-h-0 p-6 overflow-y-auto" in default
    assert "<p>Modal body</p>" in default
    large = _section(rendered, "modal-lg")
    footer = large[large.index("border-t border-solid") :]
    assert "Cancel" in footer
    assert "Save" in footer


def test_modal_attrs_and_class_reach_the_root(rendered: str) -> None:
    root = _probe(rendered, "modal-lg")
    assert 'hx-get="/probe"' in root
    assert "mt-2" in root


# --- avatar ---------------------------------------------------------------


def test_avatar_reads_its_accent_from_a_custom_property(rendered: str) -> None:
    default = _probe(rendered, "avatar-default")
    assert "var(--avatar-accent,var(--color-primary))_20%" in default
    assert "text-[color:var(--avatar-accent,var(--color-primary))]" in default
    # The override is an attribute, not a prop, so it arrives untouched.
    assert "--avatar-accent: var(--color-warning)" in _probe(rendered, "avatar-offline")


@pytest.mark.parametrize(
    ("probe", "segment"),
    [
        ("avatar-default", "w-10 h-10 text-sm"),
        ("avatar-sm", "w-8 h-8 text-xs"),
        ("avatar-lg", "w-14 h-14 text-lg"),
        ("avatar-xl", "w-20 h-20 text-2xl"),
    ],
)
def test_avatar_size_segments(rendered: str, probe: str, segment: str) -> None:
    assert segment in _probe(rendered, probe)


def test_avatar_size_segments_never_stack(rendered: str) -> None:
    small = _probe(rendered, "avatar-sm")
    assert "w-10" not in small
    assert "text-sm" not in small


def test_avatar_renders_initials_image_or_the_fallback_mark(rendered: str) -> None:
    assert "AB" in _section(rendered, "avatar-default")
    image = _section(rendered, "avatar-image")
    assert 'src="/static/img/user.png"' in image
    assert 'alt="Jane Doe"' in image
    assert "w-full h-full object-cover rounded-full" in image
    assert 'class="fas fa-user"' in _section(rendered, "avatar-fallback")


def test_avatar_slot_is_the_mark_for_a_subject_that_is_not_a_person(rendered: str) -> None:
    icon = _section(rendered, "avatar-icon")
    assert 'class="fas fa-shield-halved"' in icon
    assert "fa-user" not in icon


@pytest.mark.parametrize(
    ("probe", "colour"),
    [("avatar-online", "bg-success"), ("avatar-busy", "bg-danger"), ("avatar-offline", "bg-text-muted")],
)
def test_avatar_status_dot_colours(rendered: str, probe: str, colour: str) -> None:
    section = _section(rendered, probe)
    assert "absolute bottom-0 right-0 w-3 h-3 rounded-full border-2 border-solid border-surface" in section
    assert colour in section


def test_avatar_without_a_status_renders_no_dot(rendered: str) -> None:
    assert "absolute bottom-0 right-0" not in _section(rendered, "avatar-default")


def test_avatar_class_is_layout_only_and_lands_last(rendered: str) -> None:
    assert 'w-20 h-20 text-2xl ml-2"' in _probe(rendered, "avatar-xl")


# --- progress -------------------------------------------------------------


def test_progress_track_recipe_and_default_size(rendered: str) -> None:
    track = _probe(rendered, "progress-labelled")
    assert "w-full rounded-full overflow-hidden bg-[color-mix(in_oklab,var(--color-border)_50%,transparent)]" in track
    assert "h-2" in track
    assert 'role="progressbar"' in track
    assert 'aria-valuenow="72"' in track
    assert 'aria-valuemin="0"' in track
    assert 'aria-valuemax="100"' in track


def test_progress_size_segments_never_stack(rendered: str) -> None:
    small = _probe(rendered, "progress-sm")
    assert "h-1.5" in small
    assert "h-2" not in small
    large = _probe(rendered, "progress-lg")
    assert "h-3" in large
    assert "h-2" not in large


@pytest.mark.parametrize(
    ("probe", "accent"),
    [
        ("progress-success", "[--progress-accent:var(--color-success)]"),
        ("progress-warning", "[--progress-accent:var(--color-warning)]"),
        ("progress-danger", "[--progress-accent:var(--color-danger)]"),
    ],
)
def test_progress_variant_only_sets_the_accent_property(rendered: str, probe: str, accent: str) -> None:
    section = _section(rendered, probe)
    assert accent in section
    assert "bg-[var(--progress-accent,var(--color-primary))]" in section


def test_progress_default_variant_leaves_the_accent_at_primary(rendered: str) -> None:
    section = _section(rendered, "progress-sm")
    assert "bg-[var(--progress-accent,var(--color-primary))]" in section
    assert "--progress-accent:" not in section


def test_progress_fill_width_is_the_value(rendered: str) -> None:
    assert 'style="width: 72%"' in _section(rendered, "progress-labelled")


def test_progress_label_row_names_the_track_and_shows_a_tabular_value(rendered: str) -> None:
    header = rendered[: rendered.index('data-probe="progress-labelled"')]
    assert "flex items-baseline justify-between gap-3 mb-1.5 text-xs font-semibold text-text-muted" in header
    assert '<span class="tabular-nums text-text">72%</span>' in header
    assert 'aria-label="Coverage"' in _probe(rendered, "progress-labelled")


def test_progress_without_a_label_has_no_header_row(rendered: str) -> None:
    assert "aria-label" not in _probe(rendered, "progress-success")


# --- code block -----------------------------------------------------------


def test_code_block_shell_recipe(rendered: str) -> None:
    block = _probe(rendered, "code-named")
    assert "relative overflow-hidden bg-background border border-solid border-border rounded-[0.625rem]" in block
    assert 'x-data="{ copied: false }"' in _section(rendered, "code-named")


def test_code_block_named_header_carries_the_filename(rendered: str) -> None:
    section = _section(rendered, "code-named")
    assert "flex items-center justify-between px-4 py-2.5 bg-surface border-b border-solid" in section
    assert "text-xs font-semibold uppercase tracking-[0.05em] text-text-muted" in section
    assert "upload.sh" in section


def test_code_block_without_a_filename_floats_the_copy_control(rendered: str) -> None:
    section = _section(rendered, "code-bare")
    assert '<div class="flex items-center absolute top-2 right-2 z-10">' in section
    assert "px-4 py-2.5 bg-surface" not in section


def test_code_block_copy_state_is_one_complete_binding(rendered: str) -> None:
    section = _section(rendered, "code-named")
    assert (
        ":class=\"copied ? 'bg-success border-success text-white' : 'bg-transparent border-transparent "
        "text-text-muted" in section
    )
    # The resting colours live only in the binding, never beside it.
    assert "border border-solid cursor-pointer" in section
    assert (
        'class="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-md border border-solid'
    ) in section


def test_code_block_copies_from_its_own_root(rendered: str) -> None:
    section = _section(rendered, "code-named")
    assert "$root.querySelector('code').textContent" in section
    assert ":aria-label=\"copied ? 'Copied' : 'Copy code'\"" in section


def test_code_block_language_and_code_reach_the_pre(rendered: str) -> None:
    section = _section(rendered, "code-named")
    assert '<code class="font-mono language-bash">echo hello</code>' in section
    assert '<pre class="m-0 font-mono text-[0.8125rem] leading-[1.6] text-text">' in section
    assert '<code class="font-mono">print(1)</code>' in _section(rendered, "code-bare")


def test_code_block_cap_swaps_the_overflow_segment_and_sets_the_height(rendered: str) -> None:
    section = _section(rendered, "code-capped")
    assert "p-4 overflow-auto" in section
    assert "overflow-x-auto" not in section
    assert 'style="max-height: 12rem"' in section


def test_code_block_copyable_false_renders_no_control(rendered: str) -> None:
    section = _section(rendered, "code-capped")
    assert "clipboard" not in section
    assert "absolute top-2 right-2" not in section


# --- inline code ----------------------------------------------------------


def test_code_inline_is_the_neutral_chip_by_default(rendered: str) -> None:
    chip = _probe(rendered, "code-inline-plain")
    assert "px-1.5 py-0.5 font-mono text-[0.8125em] rounded" in chip
    assert "text-text bg-[color-mix(in_oklab,var(--color-border)_35%,transparent)]" in chip
    assert ">/.well-known/security.txt</code>" in _section(rendered, "code-inline-plain")


def test_code_inline_accent_replaces_the_whole_tint(rendered: str) -> None:
    chip = _probe(rendered, "code-inline-primary")
    assert "bg-[color-mix(in_oklab,var(--color-primary)_12%,transparent)]" in chip
    assert "text-[color-mix(in_oklab,var(--color-primary)_70%,var(--color-text))]" in chip
    assert "var(--color-border)_35%" not in chip
    assert chip.count("bg-[color-mix") == 1
    assert "ml-1" in chip


# --- token display --------------------------------------------------------


def test_token_display_shell_and_wrapper_recipe(rendered: str) -> None:
    section = _section(rendered, "token-masked")
    assert "relative flex flex-col gap-2" in _probe(rendered, "token-masked")
    assert (
        "relative flex items-stretch overflow-hidden bg-background border-[1.5px] border-solid border-border"
    ) in section
    assert "focus-within:shadow-[0_0_0_3px_color-mix(in_oklab,var(--color-primary)_10%,transparent)]" in section


def test_token_display_value_is_monospace_and_selectable(rendered: str) -> None:
    section = _section(rendered, "token-masked")
    assert "flex-1 px-4 py-3 font-mono text-[0.8125rem] font-medium leading-normal tracking-[0.025em]" in section
    assert "selection:bg-[color-mix(in_oklab,var(--color-primary)_20%,transparent)]" in section
    assert "sbom_pat_9f2Ac41ZzQ0m7Ktb" in section


def test_token_display_masked_blurs_the_value_and_adds_the_reveal_toggle(rendered: str) -> None:
    assert 'x-data="{ copied: false, masked: true }"' in _probe(rendered, "token-masked")
    section = _section(rendered, "token-masked")
    assert ":class=\"masked ? 'blur-[4px] select-none' : ''\"" in section
    assert ":aria-label=\"masked ? 'Show token' : 'Hide token'\"" in section


def test_token_display_unmasked_starts_revealed_and_has_no_toggle(rendered: str) -> None:
    assert 'x-data="{ copied: false, masked: false }"' in _probe(rendered, "token-plain")
    assert "Show token" not in _section(rendered, "token-plain")


def test_token_display_copy_reads_the_value_by_ref(rendered: str) -> None:
    section = _section(rendered, "token-masked")
    assert 'x-ref="token"' in section
    assert "$refs.token.textContent.trim()" in section
    assert ":class=\"copied ? 'bg-success text-white' : 'bg-transparent text-text-muted" in section


def test_token_display_label_row(rendered: str) -> None:
    section = _section(rendered, "token-masked")
    assert '<span class="text-[0.8125rem] font-semibold text-text">Personal access token</span>' in section
    assert "font-semibold text-text</span>" not in _section(rendered, "token-plain")


def test_token_display_with_nothing_to_do_drops_the_action_rail(rendered: str) -> None:
    section = _section(rendered, "token-nocopy")
    assert "$refs.token" not in section
    assert "border-l border-solid" not in section


# --- copy button ----------------------------------------------------------


def test_copy_button_recipe_and_copied_binding(rendered: str) -> None:
    button = _probe(rendered, "copy-default")
    assert "group inline-flex items-center gap-2 px-3.5 py-2 text-[0.8125rem] font-medium rounded-lg" in button
    assert "focus-visible:shadow-[0_0_0_2px_color-mix(in_oklab,var(--color-primary)_50%,transparent)]" in button
    assert ":class=\"copied ? 'bg-success border-success text-white' : 'bg-surface border-border text-text" in button


def test_copy_button_writes_its_value_and_confirms(rendered: str) -> None:
    button = _probe(rendered, "copy-default")
    assert "navigator.clipboard.writeText('https://sbomify.com/t/acme')" in button
    assert "setTimeout(() => copied = false, 2000)" in button


def test_copy_button_labels_are_server_rendered_and_bound(rendered: str) -> None:
    section = _section(rendered, "copy-labelled")
    assert "x-text=\"copied ? 'Copied ID' : 'Copy ID'\">Copy ID</span>" in section
    assert ":aria-label=\"copied ? 'Copied ID' : 'Copy ID'\"" in _probe(rendered, "copy-labelled")


def test_copy_button_icons_carry_their_own_colour(rendered: str) -> None:
    section = _section(rendered, "copy-default")
    assert 'class="fas fa-copy text-xs text-text-muted transition-all duration-200 group-hover:text-primary"' in section
    assert 'class="fas fa-check text-xs text-white"' in section
    assert "x-cloak" in section


def test_copy_button_forwards_attrs_and_class(rendered: str) -> None:
    button = _probe(rendered, "copy-labelled")
    assert '@click.stop="track()"' in button
    assert "ml-2" in button


# --- inline copy ----------------------------------------------------------


def test_inline_copy_is_a_monospace_chip_a_keyboard_can_reach(rendered: str) -> None:
    chip = _probe(rendered, "inline-copy")
    assert "<button" in chip
    assert 'type="button"' in chip
    assert "group inline-flex max-w-full items-center gap-1.5 px-2 py-1 font-mono" in chip
    assert "text-[0.8125rem] text-text bg-background border border-solid border-border rounded-md" in chip
    # No line-height: an arbitrary font-size attaches none to cancel, and the
    # public pages read 1.6 where the app reads 1.5.
    assert "leading-" not in chip
    assert "focus-visible:shadow-[0_0_0_2px_color-mix(in_oklab,var(--color-primary)_50%,transparent)]" in chip


def test_inline_copy_confirms_from_a_data_attribute_not_a_class(rendered: str) -> None:
    chip = _probe(rendered, "inline-copy")
    assert 'data-copied="false"' in chip
    assert ':data-copied="copied"' in chip
    assert "data-[copied=true]:bg-success" in chip
    assert "data-[copied=true]:border-success" in chip
    assert "data-[copied=true]:text-white" in chip


def test_inline_copy_icon_reads_the_same_marker_from_the_group(rendered: str) -> None:
    section = _section(rendered, "inline-copy")
    assert "text-[0.6875rem] text-text-muted transition-all duration-150 group-hover:text-primary" in section
    assert "group-data-[copied=true]:text-white" in section
    assert ":class=\"copied ? 'fa-check' : 'fa-copy'\"" in section


def test_inline_copy_announces_the_result_to_a_screen_reader(rendered: str) -> None:
    section = _section(rendered, "inline-copy")
    assert 'role="status"' in section
    assert 'aria-live="polite"' in section
    assert "x-text=\"copied ? 'Copied to clipboard' : ''\"" in section


def test_inline_copy_carries_the_value_in_its_slot(rendered: str) -> None:
    section = _section(rendered, "inline-copy")
    assert '<span x-text="value" class="min-w-0 break-all">DLyQjCBkNJkB</span>' in section


def test_inline_copy_forwards_attrs_and_class(rendered: str) -> None:
    chip = _probe(rendered, "inline-copy")
    assert '@click="copyToClipboard()"' in chip
    assert "ml-2" in _probe(rendered, "inline-copy-classed")


# --- actions menu ---------------------------------------------------------


def test_actions_menu_wrapper_holds_the_alpine_component(rendered: str) -> None:
    wrapper = _probe(rendered, "menu-default")
    assert 'class="relative inline-flex shrink-0"' in wrapper
    assert 'x-data="actionsMenu"' in wrapper
    assert '@keydown.escape.window="closeAndFocus()"' in wrapper


def test_actions_menu_trigger_is_the_library_icon_button(rendered: str) -> None:
    section = _section(rendered, "menu-default")
    assert "w-9 h-9 text-sm rounded-md" in section
    assert 'aria-label="Product actions"' in section
    assert 'x-ref="trigger"' in section
    assert '@click.stop="toggle()"' in section
    assert ':aria-expanded="open"' in section
    assert 'aria-haspopup="true"' in section


def test_actions_menu_stretch_trigger_swaps_the_shape(rendered: str) -> None:
    section = _section(rendered, "menu-stretch")
    assert "w-12 h-full min-h-10" in section
    assert "w-9 h-9" not in section
    assert 'class="fas fa-clock"' in section


def test_actions_menu_teleports_the_panel_and_nests_the_dropdown(rendered: str) -> None:
    section = _section(rendered, "menu-default")
    assert '<template x-teleport="body">' in section
    assert "fixed max-h-[min(70vh,32rem)]" in section
    assert 'role="menu"' in section
    assert "@keydown.arrow-down.prevent" in section


def test_actions_menu_panel_carries_its_positioning_hooks(rendered: str) -> None:
    section = _section(rendered, "menu-default")
    assert 'x-ref="menu"' in section
    assert 'x-show="open"' in section
    assert "x-cloak" in section
    assert ':style="style"' in section
    assert '@click="close()"' in section
    assert '@click.outside="close()"' in section


def test_actions_menu_width_lands_on_the_panel_not_the_wrapper(rendered: str) -> None:
    assert "w-56" not in _probe(rendered, "menu-default")
    assert "w-56" in _section(rendered, "menu-default")


def test_actions_menu_class_stays_on_the_wrapper(rendered: str) -> None:
    assert "ml-2" in _probe(rendered, "menu-stretch")
    # Neither the trigger nor the teleported panel inherits the wrapper's layout.
    assert "ml-2" not in _section(rendered, "menu-stretch")


def test_actions_menu_items_are_dropdown_components(rendered: str) -> None:
    section = _section(rendered, "menu-default")
    assert 'role="menuitem"' in section
    assert 'href="/advisories/new"' in section
    assert 'hx-delete="/products/1"' in section
    assert "text-danger hover:bg-[color-mix(in_oklab,var(--color-danger)_10%,transparent)]" in section
    assert "h-px my-1.5 bg-[color-mix(in_oklab,var(--color-border)_50%,transparent)]" in section
    assert "text-[0.625rem] font-bold uppercase tracking-[0.08em] text-text-muted" in section
