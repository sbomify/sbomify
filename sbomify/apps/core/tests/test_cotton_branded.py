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

That seam is wider than this library, so the guards over it are too. A public
page renders mostly main-library components, and it carries its own layout
classes; test_no_public_template_uses_a_class_the_legacy_sheets_override walks
out from the page shells that link the legacy sheet and covers everything they
reach. The collision does not need a class name either: a redeclared
--radius-* forked the whole radius scale through variables the utilities read,
which is what test_only_the_tailwind_entrypoint_declares_the_radius_scale pins.
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
TOKENS_CSS = APP_ROOT / "static" / "css" / "tokens.css"
TEMPLATE_DIRS = [APP_ROOT / "templates", *sorted((APP_ROOT / "apps").glob("*/templates"))]
COTTON_DIR = settings.COTTON_DIR
# Tailwind's --spacing, the base its numbered spacing utilities multiply.
TAILWIND_SPACING_REM = 0.25


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


def _class_names(template: Path) -> set[str]:
    """The literal class tokens a template writes.

    Variant-prefixed utilities are kept whole on purpose. ``first:pl-4`` puts the
    class ``first:pl-4`` on the element, which the legacy ``.pl-4`` selector
    cannot match, so it is not a collision; ``tables/cell.html`` relies on that.
    Only a bare name can lose.
    """
    used: set[str] = set()
    for attr in re.findall(r'class="([^"]*)"', template.read_text(errors="ignore")):
        # Drop template tags, then keep the literal utilities around them.
        used.update(re.sub(r"\{%.*?%\}|\{\{.*?\}\}", " ", attr, flags=re.S).split())
    return used


def _rem(length: str) -> float:
    length = length.strip()
    return float(length.removesuffix("rem")) if length.endswith("rem") else float(length)


def _spacing_steps_that_cannot_diverge() -> set[str]:
    """Bootstrap steps whose legacy length equals Tailwind's step of the same name.

    ``.p-2 { padding: var(--spacing-sm) !important }`` only hurts if
    ``--spacing-sm`` is not what Tailwind's ``p-2`` would have been. It is
    0.5rem and Tailwind's second step is 0.5rem, so that override paints the
    value it replaced. Step 3 upwards is where the two scales part: the legacy
    sheet runs 1rem / 1.5rem / 2rem against Tailwind's 0.75 / 1 / 1.25.

    Read out of tokens.css rather than listed, so retuning that scale moves
    which names this guard forbids instead of quietly invalidating it.
    """
    scale = dict(re.findall(r"--spacing-(\w+):\s*([^;]+);", TOKENS_CSS.read_text()))
    agree = {"0"}
    for step, name in (("1", "xs"), ("2", "sm"), ("3", "md"), ("4", "lg"), ("5", "xl")):
        if name in scale and abs(_rem(scale[name]) - int(step) * TAILWIND_SPACING_REM) < 1e-9:
            agree.add(step)
    return agree


def _collisions_that_cannot_bite() -> set[str]:
    """Legacy !important names whose declaration states the value it overrides.

    Every other name in that sheet is forbidden on a public page. These are not
    forbidden because the override is a no-op: the legacy rule and Tailwind's
    utility of the same name compute the same thing, so the page renders as the
    app does. Each group has a reason, and the spacing group has a test.
    """
    sides = ("m", "mt", "mb", "ml", "mr", "p", "pt", "pb", "pl", "pr")
    return {
        # The steps where the two spacing scales still agree, zero included.
        *(f"{side}-{step}" for side in sides for step in _spacing_steps_that_cannot_diverge()),
        # One keyword, spelled the same on both sides. There is no scale to drift.
        "flex-row",
        "flex-wrap",
        "text-left",
        "text-right",
        "text-center",
        "overflow-auto",
        "overflow-hidden",
        "overflow-visible",
        "overflow-scroll",
        "w-auto",
        "h-auto",
        # These read the very --radius-* variable Tailwind's own utility reads,
        # so they cannot part from it. Bare `rounded` is not here: the legacy
        # rule reads --radius-md where Tailwind's `rounded` is a literal 0.25rem.
        "rounded-sm",
        "rounded-lg",
    }


def _resolve(name: str) -> Path | None:
    for directory in TEMPLATE_DIRS:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _component_template(tag: str) -> Path | None:
    """``<c-forms.search-input>`` is ``components/forms/search_input.html``."""
    parts = [part.replace("-", "_") for part in tag.removeprefix("c-").split(".")]
    for suffix in (".html", ".html.j2", ".j2"):
        if found := _resolve(f"{COTTON_DIR}/{'/'.join(parts)}{suffix}"):
            return found
    return None


def _references(template: Path) -> set[Path]:
    """Every template this one pulls in: extends, include, and cotton tags."""
    text = template.read_text(errors="ignore")
    out: set[Path] = set()
    for name in re.findall(r'{%\s*(?:extends|include)\s+["\']([^"\']+)["\']', text):
        if found := _resolve(name):
            out.add(found)
    for tag in re.findall(r"<(c-[a-zA-Z0-9_.\-]+)", text):
        if tag.startswith(("c-vars", "c-slot")):
            continue
        if found := _component_template(tag):
            out.add(found)
    return out


def _templates_the_legacy_sheets_reach() -> set[Path]:
    """Every template rendered on a page that loads utilities.css.

    Derived rather than listed. The roots are the page shells that link the
    legacy sheet, which today is public_base plus the enterprise contact page;
    anything extending one of those inherits the problem, and the walk down
    through include and cotton tags collects the components they compose. A new
    public page is therefore in scope the moment it extends public_base.
    """
    templates = [path for directory in TEMPLATE_DIRS for path in directory.rglob("*") if path.is_file()]
    reached = {path for path in templates if LEGACY_CSS.name in path.read_text(errors="ignore")}
    growing = True
    while growing:
        growing = False
        for path in templates:
            if path in reached:
                continue
            for name in re.findall(r'{%\s*extends\s+["\']([^"\']+)["\']', path.read_text(errors="ignore")):
                if _resolve(name) in reached:
                    reached.add(path)
                    growing = True
    queue = list(reached)
    while queue:
        for reference in _references(queue.pop()):
            if reference not in reached:
                reached.add(reference)
                queue.append(reference)
    return reached


def test_the_legacy_sheet_still_looks_the_way_this_guard_assumes() -> None:
    """If utilities.css is deleted, the guard below must fail loudly, not pass."""
    assert LEGACY_CSS.exists(), "utilities.css moved; update or retire the collision guard"
    assert len(_legacy_important_classes()) > 50


def test_the_spacing_steps_this_guard_forgives_are_the_ones_that_match() -> None:
    """_collisions_that_cannot_bite is arithmetic, so the arithmetic gets a test.

    Steps 0, 1 and 2 are forgiven in about forty templates. They are only safe
    while --spacing-xs and --spacing-sm hold the lengths Tailwind's steps hold,
    which is exactly the "one prop away" risk this file exists to close. If that
    scale is retuned, the step drops out of the forgiven set here and the guard
    starts naming every template using it.
    """
    agree = _spacing_steps_that_cannot_diverge()
    assert {"0", "1", "2"} <= agree, f"the legacy spacing scale moved under the guard: {agree}"
    assert not {"3", "4", "5"} & agree, "the scales converged; retire the arbitrary-value workarounds"


def test_no_component_uses_a_class_the_legacy_sheets_override() -> None:
    """A colliding utility loses only on public pages, which is where these run.

    Tailwind's p-4 is 1rem; the legacy .p-4 is a spacing variable and carries
    !important, so it wins wherever both are loaded. The same trap holds for
    rounded-lg, shadow-sm, w-50 and text-muted. Components stay off those
    names; px-*, py-*, gap-*, rounded-xl and the token utilities are clear.

    This set carries no forgiveness: a branded component is written for the
    public pages, so it has no excuse for naming one of those classes at all.
    """
    legacy = _legacy_important_classes()
    offenders = {
        template.relative_to(BRANDED_DIR).as_posix(): collisions
        for template in sorted(BRANDED_DIR.rglob("*.html"))
        if (collisions := _class_names(template) & legacy)
    }
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


def test_a_credential_sits_on_the_panel_rather_than_restating_it(rendered: str) -> None:
    """It nests c-branded.surface, so the panel recipe has one home."""
    tile = _classes(rendered, "div", 'data-probe="credential"')
    assert "rounded-xl" in tile
    assert "bg-surface" in tile
    assert "border-border" in tile
    assert "py-6" in tile
    assert "py-4" not in tile


def test_a_credential_stretches_its_link_over_the_whole_tile(rendered: str) -> None:
    """Same trick as a row, and for the same reason: one anchor to repaint."""
    tile = rendered[rendered.index('data-probe="credential"') :]
    anchor = tile[tile.index("<a ") : tile.index("</a>")]
    assert "before:absolute before:inset-0" in anchor
    assert "data-button" in anchor
    assert "ISO 27001" in anchor
    assert "relative" in _classes(rendered, "div", 'data-probe="credential"')


def test_a_credential_seal_is_decorative(rendered: str) -> None:
    """The label underneath already names it; announcing it twice is noise."""
    tile = rendered[rendered.index('data-probe="credential"') :]
    image = tile[tile.index("<img") : tile.index(">", tile.index("<img")) + 1]
    assert 'alt=""' in image
    assert 'aria-hidden="true"' in image


def test_a_credential_without_a_seal_still_shows_what_it_is(rendered: str) -> None:
    """A certification we have no artwork for is better shown than hidden."""
    tile = rendered[rendered.index('data-probe="credential-imageless"') :]
    tile = tile[: tile.index("data-probe=", 20)] if "data-probe=" in tile[20:] else tile
    assert "<img" not in tile
    assert "SOC 2 Type II" in tile


def test_a_credential_is_not_branded(rendered: str) -> None:
    """A seal is read, not acted on, so a pale brand would make it vanish."""
    tile = _classes(rendered, "div", 'data-probe="credential"')
    assert not any("var(--brand)" in utility for utility in tile)


def test_no_public_template_uses_a_class_the_legacy_sheets_override() -> None:
    """The same guard, over everything the legacy sheets actually reach.

    A branded component is not the only thing that can name a colliding
    utility. A page composing them writes layout classes too, and so does every
    main-library component a public page happens to render, which is most of
    them: 92 of the 209 named one of these classes while this guard watched
    three trust-centre pages and the branded directory. mb-4 came out at 24px on
    a public product page against 16px in the app, and pt-5 at 32px against
    20px, on shipped markup nothing was looking at.

    Scope is computed, not listed, so a new public page cannot land outside it.
    What is forgiven is also computed: a name whose legacy declaration states
    the length it overrides renders the same on both sides, and
    _collisions_that_cannot_bite says which those are and why. Everything else
    is an offender, with no per-template allowlist to grow.
    """
    legacy = _legacy_important_classes() - _collisions_that_cannot_bite()
    offenders = {
        template.relative_to(APP_ROOT).as_posix(): collisions
        for template in sorted(_templates_the_legacy_sheets_reach())
        if (collisions := _class_names(template) & legacy)
    }
    assert not offenders, (
        "classes the legacy !important sheets would override on a public page: "
        f"{offenders}. Use px-*/py-*/gap-*, an arbitrary value such as mb-[1rem], "
        "or a token utility instead."
    )


def test_only_the_tailwind_entrypoint_declares_the_radius_scale() -> None:
    """The scale has one home, because a second one forks it silently.

    public_base.htmx.j2 and tokens.css both used to restate --radius-*. Both are
    unlayered and Tailwind publishes its theme inside @layer theme, so both beat
    it whatever the source order: rounded-xl measured 16px on a public page
    against 12px in the app, on every card, table frame, stat card and alert.
    rounded-xl is the radius AGENTS.md names as the safe one, and the rule that
    was written to prevent this could not see it, because the class name was
    never the problem.
    """
    searched = [
        *sorted((APP_ROOT / "static" / "css").rglob("*.css")),
        *sorted(_templates_the_legacy_sheets_reach()),
    ]
    offenders = {
        path.relative_to(APP_ROOT).as_posix(): sorted(set(found))
        for path in searched
        if (found := re.findall(r"(--radius-[a-z0-9]+)\s*:", path.read_text(errors="ignore")))
    }
    assert not offenders, f"--radius-* belongs to sbomify/assets/css/tailwind.src.css alone, found in: {offenders}"


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
