"""Render contract for the branded component set.

These components are shown to our users' users, so two things are pinned here
that the main library does not have to worry about.

First, the brand reaches the page as two custom properties and the ink is
measured rather than chosen. A whole trust centre page is one brand, so
public_base publishes them at :root; c-branded.theme is the same scope for a
smaller piece, such as the preview on the branding settings tab. Buttons are not
in this library: the trust centre uses the app's own, so there is no branded
button to test here. A workspace can
colour what a reader acts on and nothing they read against.

Second, branded components render on the public pages, which still load seven
legacy stylesheets carrying 140 !important declarations. A class name that
collides with one of those loses, silently, only on the pages this library
exists for. test_no_component_uses_a_class_the_legacy_sheets_override is the
guard.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.template.loader import render_to_string

from sbomify.apps.teams.branding import DEFAULT_ACCENT_COLOR, DEFAULT_BRAND_COLOR

APP_ROOT = Path(settings.BASE_DIR) / "sbomify"
BRANDED_DIR = APP_ROOT / "templates" / "components" / "branded"
LEGACY_CSS = APP_ROOT / "static" / "css" / "utilities.css"


@pytest.fixture(scope="module")
def rendered() -> str:
    return render_to_string("core/cotton_probes/branded.html.j2", {})


def _open_tag(rendered: str, tag: str, marker: str) -> str:
    chunks = [part for part in rendered.split(f"<{tag}") if marker in part]
    assert chunks, f"no <{tag}> holds {marker!r}"
    return chunks[0][: chunks[0].index(">") + 1]


def _classes(rendered: str, tag: str, marker: str) -> set[str]:
    open_tag = _open_tag(rendered, tag, marker)
    start = open_tag.index('class="') + len('class="')
    return set(open_tag[start : open_tag.index('"', start)].split())


# ── The brand scope ─────────────────────────────────────────────────────────


def test_theme_publishes_the_brand_and_its_ink(rendered: str) -> None:
    """Two properties, not a palette: a fill and the text that goes on it."""
    scope = _open_tag(rendered, "div", 'data-probe="theme-dark"')
    assert "--brand: #25293F" in scope
    assert "--brand-ink: #ffffff" in scope


def test_theme_measures_the_ink_rather_than_assuming_white(rendered: str) -> None:
    """A pale brand gets dark text, which is the point of the helper."""
    scope = _open_tag(rendered, "div", 'data-probe="theme-light"')
    assert "--brand: #FDE68A" in scope
    assert f"--brand-ink: {DEFAULT_BRAND_COLOR}" in scope


def test_theme_without_a_brand_falls_back_to_the_platform_accent(rendered: str) -> None:
    """An unbranded workspace still renders as sbomify, not as gray."""
    scope = _open_tag(rendered, "div", 'data-probe="theme-none"')
    assert f"--brand: {DEFAULT_ACCENT_COLOR}" in scope
    assert "--brand-ink: #ffffff" in scope


def test_theme_replaces_a_css_injection_rather_than_escaping_it(rendered: str) -> None:
    """The brand lands in a style attribute, so a payload must not survive."""
    scope = _open_tag(rendered, "div", 'data-probe="theme-evil"')
    assert "</style>" not in scope
    assert "script" not in scope.lower()
    assert f"--brand: {DEFAULT_ACCENT_COLOR}" in scope


# ── What may and may not wear the brand ─────────────────────────────────────


def test_surface_is_not_brandable(rendered: str) -> None:
    """Colour goes on what a reader acts on, never the ground they read against."""
    surface = _classes(rendered, "div", 'data-probe="surface"')
    assert "bg-surface" in surface
    assert "border-border" in surface
    assert not any("var(--brand)" in utility for utility in surface)


def test_severity_keeps_the_platform_colours(rendered: str) -> None:
    """Red must mean critical on every trust centre, so it is not brandable."""
    badge = _classes(rendered, "span", 'data-probe="badge-critical"')
    assert "var(--tone)" in " ".join(badge)
    assert not any("var(--brand)" in utility for utility in badge)


def test_a_badge_the_workspace_owns_may_take_the_brand(rendered: str) -> None:
    """As a fill under the measured ink, never as brand-coloured text."""
    badge = _classes(rendered, "span", 'data-probe="badge-brand"')
    assert "bg-[var(--brand)]" in badge
    assert "text-[var(--brand-ink)]" in badge
    assert "text-[var(--brand)]" not in badge


def test_the_brand_is_never_used_as_text_or_an_icon_colour() -> None:
    """The rule a pale brand breaks: brand-on-brand-tint is invisible.

    A fill is safe because --brand-ink was measured against it. Colouring text
    or an icon with --brand is not, because what sits behind it is whatever the
    surface happens to be. Only the nav underline may take the raw brand, and
    that is a 2px rule against the page, not something being read.
    """
    offenders: dict[str, list[str]] = {}
    for template in sorted(BRANDED_DIR.rglob("*.html")):
        if template.name == "nav_item.html":
            continue
        bad = [used for used in re.findall(r"text-\[var\(--brand\)\]", template.read_text())]
        if bad:
            offenders[template.relative_to(BRANDED_DIR).as_posix()] = bad
    assert not offenders, f"brand used as a text colour: {offenders}"


def test_current_nav_item_is_marked_for_a_reader_and_a_screen_reader(rendered: str) -> None:
    current = _open_tag(rendered, "a", 'data-probe="nav-current"')
    assert 'aria-current="page"' in current
    assert "border-[var(--brand)]" in current
    other = _open_tag(rendered, "a", 'data-probe="nav-other"')
    assert "aria-current" not in other
    assert "border-transparent" in other


# ── The legacy-collision guard ──────────────────────────────────────────────


def _legacy_important_classes() -> set[str]:
    """Class names in utilities.css whose declarations carry !important."""
    css = LEGACY_CSS.read_text()
    important: set[str] = set()
    for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector, body = block.group(1), block.group(2)
        if "!important" not in body:
            continue
        important.update(re.findall(r"\.([a-zA-Z0-9_-]+)", selector))
    return important


def test_the_legacy_sheet_still_looks_the_way_this_guard_assumes() -> None:
    """If utilities.css is deleted, the guard below must fail loudly, not pass."""
    assert LEGACY_CSS.exists(), "utilities.css moved; update or retire the collision guard"
    assert len(_legacy_important_classes()) > 50


def test_no_component_uses_a_class_the_legacy_sheets_override() -> None:
    """A colliding utility loses only on public pages, which is where these run.

    Tailwind's p-4 is 1rem; the legacy .p-4 is a spacing variable and carries
    !important, so it wins wherever both are loaded. The same trap holds for
    rounded-lg, shadow-sm, w-50 and text-muted. Components stay off those
    names; px-*, py-*, gap-*, rounded-xl and the token utilities are clear.
    """
    legacy = _legacy_important_classes()
    offenders: dict[str, set[str]] = {}

    for template in sorted(BRANDED_DIR.rglob("*.html")):
        used: set[str] = set()
        for attr in re.findall(r'class="([^"]*)"', template.read_text()):
            # Drop template tags, then keep the literal utilities around them.
            for token in re.sub(r"\{%.*?%\}|\{\{.*?\}\}", " ", attr, flags=re.S).split():
                used.add(token.split(":")[-1] if ":" in token and "[" not in token else token)
        if collisions := used & legacy:
            offenders[template.relative_to(BRANDED_DIR).as_posix()] = collisions

    assert not offenders, f"classes the legacy !important sheets would override: {offenders}"


# ── The rebuilt set ─────────────────────────────────────────────────────────


def test_badge_drives_every_tone_from_one_recipe(rendered: str) -> None:
    """One set of utilities, only the colour varies, so a ramp cannot drift."""
    critical = _open_tag(rendered, "span", 'data-probe="badge-critical"')
    assert "--tone: var(--color-severity-critical)" in critical
    assert "bg-[color-mix(in_oklab,var(--tone)_14%,transparent)]" in critical


def test_badge_covers_the_whole_severity_ramp(rendered: str) -> None:
    """medium and low exist in the tokens, so they must exist here."""
    for level in ("critical", "high", "medium", "low"):
        assert f"--tone: var(--color-severity-{level})" in rendered, level


def test_a_flush_surface_clips_so_a_square_child_cannot_spill(rendered: str) -> None:
    """The panel owns the radius, so the panel owns the clipping.

    A severity spine is square and the corner is not. Without the clip the
    colour draws past the corner, which is the bug this replaced.
    """
    flush = _classes(rendered, "div", 'data-probe="list"')
    assert "overflow-clip" in flush
    assert "rounded-xl" in flush
    # A padded panel is not clipped, so a focus ring may still overhang.
    padded = _classes(rendered, "div", 'data-probe="surface"')
    assert "overflow-clip" not in padded


def test_the_spine_spans_the_row_and_takes_the_platform_ramp(rendered: str) -> None:
    spine = _open_tag(rendered, "span", 'data-probe="row-critical"')
    row = rendered[rendered.index('data-probe="row-critical"') :]
    assert "absolute inset-y-0 left-0 w-[3px]" in row
    assert "--tone: var(--color-severity-critical)" in row
    assert "var(--brand)" not in row[: row.index("</span>")]
    assert spine is not None


def test_a_linked_row_wraps_only_its_heading(rendered: str) -> None:
    """The legacy sheet repaints anchors, so it gets one element, not the row.

    The stretched pseudo element is what keeps the whole row clickable.
    """
    row = rendered[rendered.index('data-probe="row-critical"') :]
    anchor = row[row.index("<a ") : row.index("</a>")]
    assert "before:absolute before:inset-0" in anchor
    assert "text-text" in anchor
    assert "Heap overflow in libfoo" in anchor


def test_the_eyebrow_does_not_restyle_what_it_holds(rendered: str) -> None:
    """It usually holds a badge, and text-transform inherits."""
    header = rendered[rendered.index('data-probe="page-header"') :]
    eyebrow = header[: header.index("</h1>")]
    assert "uppercase" not in eyebrow


def test_a_page_header_and_a_section_header_are_different_components() -> None:
    """Not one component with a size prop, which would let either sit in the
    other's place. Neither file may take a prop that turns it into the other."""
    for name in ("page_header", "section_header"):
        vars_line = (BRANDED_DIR / f"{name}.html").read_text()
        vars_line = vars_line[vars_line.index("<c-vars") : vars_line.index("/>")]
        assert "size" not in vars_line, name
        assert "variant" not in vars_line, name


def test_figures_are_never_branded(rendered: str) -> None:
    """A number is read, not acted on, so a pale brand would make it vanish."""
    stat = _classes(rendered, "div", 'data-probe="stat"')
    assert not any("var(--brand)" in utility for utility in stat)


def test_no_public_template_uses_a_class_the_legacy_sheets_override() -> None:
    """The same guard, applied to the pages rather than the components.

    A component is not the only thing that can name a colliding utility: a page
    composing them writes layout classes too, and these pages are exactly the
    ones that load the legacy sheets. mb-4 slipped through this way, resolving
    to the legacy spacing variable rather than Tailwind's 1rem.

    Pre-existing offenders are listed rather than fixed, so the guard can be
    strict about new ones without turning red on markup this branch did not
    write. Shrink the list, never grow it.
    """
    known = {
        "components/trust_center/advisories_browse.html.j2": {"flex-wrap", "mb-2", "mb-3", "mt-1", "p-2"},
        "workspace_public.html.j2": {"flex-wrap", "mt-1"},
        # Not migrated yet; these go when that page is.
        "trust_center_advisory_detail.html.j2": {
            "flex-wrap",
            "m-0",
            "mb-3",
            "mb-5",
            "ml-1",
            "mt-1",
            "mt-4",
        },
    }
    legacy = _legacy_important_classes()
    trust_center = [
        APP_ROOT / "apps/core/templates/core/workspace_public.html.j2",
        APP_ROOT / "apps/core/templates/core/trust_center_advisories.html.j2",
        APP_ROOT / "apps/core/templates/core/trust_center_advisory_detail.html.j2",
        *sorted((APP_ROOT / "apps/core/templates/core/components/trust_center").glob("*.j2")),
    ]
    offenders: dict[str, set[str]] = {}
    for template in trust_center:
        if not template.exists():
            continue
        used: set[str] = set()
        for attr in re.findall(r'class="([^"]*)"', template.read_text()):
            for token in re.sub(r"\{%.*?%\}|\{\{.*?\}\}", " ", attr, flags=re.S).split():
                used.add(token.split(":")[-1] if ":" in token and "[" not in token else token)
        key = template.as_posix().split("core/templates/core/")[-1]
        if fresh := (used & legacy) - known.get(key, set()):
            offenders[key] = fresh

    assert not offenders, f"classes the legacy !important sheets would override: {offenders}"


def test_no_template_has_a_comment_that_renders_as_page_text() -> None:
    """Django's comment tag is single-line: {# … #} split across lines is not a
    comment, and the text lands on the page.

    One shipped this way, visible on the component page, so the rule gets a
    test rather than only a warning in AGENTS.md. Use {% comment %} … {%
    endcomment %} for anything that does not fit on one line.
    """
    offenders: list[str] = []
    roots = [APP_ROOT.parent / "sbomify"]
    for root in roots:
        for template in [*root.rglob("*.j2"), *root.rglob("*.html")]:
            path = template.as_posix()
            if "node_modules" in path or "/dist/" in path or "/staticfiles/" in path:
                continue
            for number, line in enumerate(template.read_text(errors="ignore").splitlines(), 1):
                if "{#" in line and "#}" not in line.split("{#", 1)[1]:
                    offenders.append(f"{template.relative_to(root).as_posix()}:{number}")

    assert not offenders, "multi-line {# #} comments render as page text: " + ", ".join(offenders)
