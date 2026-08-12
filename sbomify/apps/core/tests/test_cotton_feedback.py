"""Render contract for the cotton feedback component set.

The probe template exercises every component in components/feedback; these tests
pin the shells, the accent each variant emits and the segments that must never
stack, so pages can rely on the components without ever writing a class
themselves.
"""

import pytest
from django.template.loader import render_to_string


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string("core/cotton_probes/feedback.html.j2")


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


# --- alert ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("probe", "accent"),
    [
        ("alert-info", "[--alert-accent:var(--color-primary)]"),
        ("alert-success", "[--alert-accent:var(--color-success)]"),
        ("alert-warning", "[--alert-accent:var(--color-warning)]"),
        ("alert-danger", "[--alert-accent:var(--color-danger)]"),
    ],
)
def test_alert_variant_sets_its_accent(rendered: str, probe: str, accent: str) -> None:
    assert accent in _probe(rendered, probe)


def test_alert_shell_reads_the_accent_for_tint_border_and_text(rendered: str) -> None:
    info = _probe(rendered, "alert-info")
    assert "bg-[linear-gradient(135deg,color-mix(in_oklab,var(--alert-accent)_10%,transparent)_0%," in info
    assert "border-[color-mix(in_oklab,var(--alert-accent)_20%,transparent)]" in info
    assert "text-[color-mix(in_oklab,var(--alert-accent)_60%,var(--color-text))]" in info
    assert 'role="alert"' in info


def test_alert_default_variant_is_info(rendered: str) -> None:
    assert "[--alert-accent:var(--color-primary)]" in _probe(rendered, "alert-info")
    assert "fas fa-info-circle" in _section(rendered, "alert-info")


@pytest.mark.parametrize(
    ("probe", "glyph"),
    [
        ("alert-success", "fas fa-check-circle"),
        ("alert-warning", "fas fa-exclamation-triangle"),
        ("alert-danger", "fas fa-bomb"),
    ],
)
def test_alert_icon_follows_the_variant_unless_overridden(rendered: str, probe: str, glyph: str) -> None:
    assert glyph in _section(rendered, probe)


def test_alert_padding_segments_never_conflict(rendered: str) -> None:
    plain = _probe(rendered, "alert-info")
    assert "px-5" in plain
    assert "pr-12" not in plain
    dismissible = _probe(rendered, "alert-warning")
    assert "relative pl-5 pr-12" in dismissible
    assert "px-5" not in dismissible


def test_alert_dismiss_keeps_its_alpine_hook_and_label(rendered: str) -> None:
    button = _section(rendered, "alert-warning")
    assert "@click=\"$el.closest('[data-alert]')?.remove()\"" in button
    assert 'aria-label="Dismiss"' in button


def test_alert_action_slot_is_the_rows_last_item(rendered: str) -> None:
    """The control that resolves the notice sits after the message, not in it."""
    body = _section(rendered, "alert-actioned")
    message = body.index('<p class="text-sm m-0">')
    action = body.index("Manage")
    assert message < action
    # Outside the content column, so the row's flex puts it at the end.
    assert body.index("</div>", message) < action


def test_alert_body_slot_replaces_the_paragraph(rendered: str) -> None:
    """A notice that explains itself at length cannot live inside a p element."""
    body = _section(rendered, "alert-body")
    assert '<p class="text-sm m-0">' not in body
    assert '<p class="mb-2">No vulnerability scan data found for this SBOM.</p>' in body
    assert "<pre" in body
    # The title still leads the column.
    assert body.index("No Scan Data Available") < body.index("<pre")


def test_alert_mark_slot_replaces_the_glyph(rendered: str) -> None:
    """A scan in flight is marked by the brand loader, which is not a glyph class."""
    marked = _section(rendered, "alert-marked")
    assert "brand-loader-stand-in" in marked
    assert "fa-info-circle" not in marked
    # It keeps the glyph's box and ink, so the row does not shift under it.
    assert "shrink-0 w-5 h-5 mt-0.5 text-[var(--alert-accent,currentColor)]" in marked


def test_alert_without_an_action_renders_nothing_after_the_message(rendered: str) -> None:
    plain = _section(rendered, "alert-info")
    # From the message to the next alert's root: only closing tags in between.
    tail = plain[plain.index("Info body") : plain.index("<div")]
    assert tail.count("<") == tail.count("</")


def test_alert_title_and_slot_render(rendered: str) -> None:
    body = _section(rendered, "alert-success")
    assert '<p class="font-semibold mb-1">Saved</p>' in body
    assert '<p class="text-sm m-0">Success body</p>' in body


def test_alert_forwards_attrs_and_caller_class(rendered: str) -> None:
    danger = _probe(rendered, "alert-danger")
    assert 'hx-get="/probe"' in danger
    assert '@click.stop="fire()"' in danger
    assert "mb-4" in danger


# --- callout --------------------------------------------------------------


def test_callout_border_consumes_the_accent_with_a_neutral_fallback(rendered: str) -> None:
    plain = _probe(rendered, "callout-plain")
    assert "border-[color-mix(in_oklab,var(--callout-accent,var(--color-border))_30%,var(--color-border))]" in plain
    assert "[--callout-accent" not in plain


def test_callout_warning_sets_the_accent(rendered: str) -> None:
    assert "[--callout-accent:var(--color-warning)]" in _probe(rendered, "callout-warning")


def test_callout_parts_carry_their_padding(rendered: str) -> None:
    assert "flex items-start gap-3 px-4 pt-4 pb-0" in _probe(rendered, "callout-header")
    assert "px-4 pt-3 pb-4" in _probe(rendered, "callout-body")


def test_callout_body_appends_caller_layout_classes(rendered: str) -> None:
    assert "px-4 pt-3 pb-4 flex flex-wrap gap-2" in _probe(rendered, "callout-body")


def test_callout_nests_its_parts_in_order(rendered: str) -> None:
    start = rendered.index('data-probe="callout-warning"')
    assert start < rendered.index("Callout heading") < rendered.index("Callout controls")


# --- empty state ----------------------------------------------------------


def test_empty_state_padding_segments_never_conflict(rendered: str) -> None:
    default = _probe(rendered, "empty-default")
    assert "px-8 py-12" in default
    compact = _probe(rendered, "empty-compact")
    assert "p-8" in compact
    assert "py-12" not in compact


def test_empty_state_medallion_default_recipe(rendered: str) -> None:
    medallion = _section(rendered, "empty-default")
    assert "w-20 h-20 text-2xl mb-6" in medallion
    assert "text-primary" in medallion
    assert "color-mix(in_oklab,var(--color-primary)_15%,transparent)" in medallion


def test_empty_state_medallion_size_and_tone_segments(rendered: str) -> None:
    medallion = _section(rendered, "empty-compact")
    assert "w-16 h-16 text-xl mb-4" in medallion
    assert "w-20" not in medallion
    assert "color-mix(in_oklab,var(--color-border)_30%,transparent)" in medallion
    assert "text-text-muted" in medallion
    assert "text-primary" not in medallion


def test_empty_state_mark_takes_its_size_from_the_medallion(rendered: str) -> None:
    """The mark carries no size of its own, so the small medallion holds the
    small mark rather than the full-size one shrunk into it."""
    assert '<i class="fas fa-cube" aria-hidden="true">' in _section(rendered, "empty-default")
    assert '<i class="fas fa-address-card" aria-hidden="true">' in _section(rendered, "empty-untitled")


def test_empty_state_without_a_title_writes_no_heading(rendered: str) -> None:
    untitled = _section(rendered, "empty-untitled")
    assert "<h3" not in untitled
    assert "No entities in this profile" in untitled


def test_empty_state_title_message_and_secondary_link(rendered: str) -> None:
    body = _section(rendered, "empty-default")
    assert "No components yet" in body
    assert "Create your first component." in body
    assert 'href="/docs"' in body
    assert "or read the docs" in body


def test_empty_state_slot_holds_a_real_button_component(rendered: str) -> None:
    action = _section(rendered, "empty-default")
    assert 'href="/components/new"' in action
    assert "bg-[linear-gradient(135deg,var(--color-primary)_0%,var(--color-primary-dark)_100%)]" in action


# --- skeleton -------------------------------------------------------------


@pytest.mark.parametrize(
    ("probe", "shape"),
    [
        ("skeleton-text", "h-4 mb-2.5 rounded-sm last:w-[70%] last:mb-0"),
        ("skeleton-title", "h-6 w-[60%] mb-3 rounded-md"),
        ("skeleton-avatar", "w-12 h-12 shrink-0 rounded-full"),
        ("skeleton-button", "h-10 w-28 rounded-lg"),
        ("skeleton-image", "w-full h-48 rounded-lg"),
    ],
)
def test_skeleton_type_segments(rendered: str, probe: str, shape: str) -> None:
    assert shape in _probe(rendered, probe)


def test_skeleton_shimmer_is_shared_by_every_shape(rendered: str) -> None:
    for probe in ("skeleton-text", "skeleton-avatar", "skeleton-image"):
        tag = _probe(rendered, probe)
        assert "animate-[shimmer_1.5s_ease-in-out_infinite]" in tag
        assert "bg-[length:200%_100%]" in tag


def test_skeleton_type_segments_never_conflict(rendered: str) -> None:
    avatar = _probe(rendered, "skeleton-avatar")
    assert "rounded-md" not in avatar
    assert "h-4" not in avatar


def test_skeleton_width_and_height_stay_inline(rendered: str) -> None:
    assert 'style="width: 7rem;' in _probe(rendered, "skeleton-button")
    assert 'style="height: 9rem;' in _probe(rendered, "skeleton-image")


def test_skeleton_paragraph_stacks_text_rows_and_shortens_the_last(rendered: str) -> None:
    assert "space-y-2 mt-2" in _probe(rendered, "skeleton-paragraph")
    rows = _section(rendered, "skeleton-paragraph")
    assert rows.count("width: 100%;") == 1
    assert rows.count("width: 60%;") == 1
    assert rows.count("animate-[shimmer_1.5s_ease-in-out_infinite]") == 2


def test_skeleton_paragraph_rows_do_not_inherit_the_wrapper_class(rendered: str) -> None:
    # class is declared bare, so it falls through from the surrounding context
    # unless the component clears it: the rows must not pick up the wrapper's.
    assert "mt-2" not in _section(rendered, "skeleton-paragraph")


# --- loading --------------------------------------------------------------


def test_loading_panel_stacks_and_uses_the_large_brand_loader(rendered: str) -> None:
    panel = _probe(rendered, "loading-panel")
    assert "flex flex-col items-center justify-center py-12" in panel
    body = _section(rendered, "loading-panel")
    assert "tw-brand-loader tw-loader-lg text-primary" in body
    assert '<p class="mt-3 text-text-muted">Loading artifacts…</p>' in body


def test_loading_row_puts_the_loader_beside_the_message(rendered: str) -> None:
    row = _probe(rendered, "loading-row")
    assert "flex items-center justify-center py-2" in row
    assert "flex-col" not in row
    body = _section(rendered, "loading-row")
    assert "tw-brand-loader tw-loader-md text-primary" in body
    assert '<span class="ml-3 text-sm text-text-muted">Refreshing…</span>' in body


def test_loading_forwards_attrs(rendered: str) -> None:
    assert 'hx-swap-oob="true"' in _probe(rendered, "loading-row")


# --- toast ----------------------------------------------------------------


def test_toast_shell_and_accent(rendered: str) -> None:
    success = _probe(rendered, "toast-success")
    assert "min-w-80 max-w-md" in success
    assert "animate-[slideInRight_0.3s_cubic-bezier(0.4,0,0.2,1)]" in success
    assert "[--toast-accent:var(--color-success)]" in success
    assert 'role="alert"' in success
    assert "[--toast-accent:var(--color-danger)]" in _probe(rendered, "toast-danger")


def test_toast_icon_tint_reads_the_accent(rendered: str) -> None:
    icon = _section(rendered, "toast-success")
    assert "fas fa-check-circle" in icon
    assert "bg-[color-mix(in_oklab,var(--toast-accent,var(--color-primary))_12%,transparent)]" in icon


def test_toast_title_and_message(rendered: str) -> None:
    body = _section(rendered, "toast-success")
    assert '<p class="text-[0.9375rem] font-semibold text-text mb-0.5">Saved</p>' in body
    assert '<p class="text-sm leading-[1.4] text-text-muted">Component updated.</p>' in body


def test_toast_close_is_on_by_default_and_can_be_turned_off(rendered: str) -> None:
    assert "this.closest('[data-toast]')?.remove()" in _section(rendered, "toast-success")
    danger = _section(rendered, "toast-danger")
    danger = danger[: danger.index('id="toast-container"')]
    assert "remove()" not in danger
    assert 'aria-label="Dismiss"' not in danger


# --- toast container ------------------------------------------------------


def test_toast_container_keeps_its_event_driven_alpine_markup(rendered: str) -> None:
    body = rendered[rendered.index('id="toast-container"') :]
    assert '@toast.window="addToast($event.detail)"' in body
    assert 'aria-live="polite"' in body
    assert '<template x-for="toast in toasts" :key="toast.id">' in body
    assert 'x-transition:enter-start="opacity-0 translate-x-8"' in body
    assert 'x-text="toast.title"' in body
    assert '@click="show = false; $nextTick(() => removeToast(toast.id))"' in body


def test_toast_container_binds_only_the_accent_and_the_glyph(rendered: str) -> None:
    body = rendered[rendered.index('id="toast-container"') :]
    assert ":class=\"{ '[--toast-accent:var(--color-success)]': toast.type === 'success'" in body
    assert ":class=\"{ 'fas fa-check-circle': toast.type === 'success'" in body
    # The surface itself is static, exactly as c-feedback.toast renders it.
    assert "pointer-events-auto flex items-start gap-3 py-4 px-4.5 bg-surface rounded-xl" in body


def test_toast_container_surface_matches_the_toast_component(rendered: str) -> None:
    shared = (
        "bg-surface rounded-xl border border-solid border-border "
        "shadow-[0_10px_40px_-10px_rgb(0_0_0/0.3)] min-w-80 max-w-md "
        "animate-[slideInRight_0.3s_cubic-bezier(0.4,0,0.2,1)]"
    )
    assert rendered.count(shared) == 3  # two toasts and the container's template
