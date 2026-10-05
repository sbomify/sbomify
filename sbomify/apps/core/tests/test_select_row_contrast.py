"""A greyed-out select row must stay readable, after the filter, in both themes.

``c-layout.select-row`` drains the colour from a row whose control is disabled.
It used to do that with ``opacity-50 grayscale``, which on the plugins page landed
on every plan-blocked row -- including the badge naming the plan required and the
button that resolves it. Measured from rendered pixels, the badge sat at 1.4:1 and
the 12px description at 2.0:1 against a 4.5:1 AA floor: the one sentence telling a
customer what to buy was the least readable text on the page.

``opacity`` is gone and ``grayscale`` stays, but grayscale is **not** a free pass.
CSS filters apply their matrix to non-linear sRGB channel values, while WCAG
linearises sRGB before weighting it, so the two are not the same operation and
greying genuinely moves relative luminance -- pure red drops from 0.213 to 0.037.
For this row's own palette it moves contrast in both directions: the plan-required
badge goes 4.66 -> 5.01 in light and 6.90 -> 6.49 in dark.

So the numbers are pinned here rather than argued from an invariant. Every
foreground the row greys is checked against the background it is actually greyed
against, after the filter, in both themes. A palette change that pushes one of
them under AA fails here instead of on a customer's screen.
"""

import re
from pathlib import Path

import pytest

STYLESHEET = Path(__file__).resolve().parents[3] / "assets" / "css" / "tailwind.src.css"
COMPONENTS = Path(__file__).resolve().parents[3] / "templates" / "components"
SELECT_ROW = COMPONENTS / "layout" / "select_row.html"

# WCAG 2.1 for text under 24px. The row's smallest text is the 12px badge and the
# 12px plugin description; nothing it greys is large-text.
SMALL_TEXT = 4.5


def _relative_luminance(rgb: tuple[float, ...]) -> float:
    channels = []
    for value in rgb:
        srgb = value / 255
        channels.append(srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(foreground: tuple[float, ...], background: tuple[float, ...]) -> float:
    lighter, darker = sorted((_relative_luminance(foreground), _relative_luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def over(colour: tuple[float, ...], surface: tuple[float, ...], tint: float) -> tuple[float, ...]:
    """The tint a badge paints behind its own text."""
    return tuple(tint * colour[i] + (1 - tint) * surface[i] for i in range(3))


def greyed(rgb: tuple[float, ...]) -> tuple[float, float, float]:
    """``filter: grayscale(1)`` as a browser applies it.

    The luminance coefficients, but weighted over the *non-linear* sRGB channels:
    CSS shorthand filters run in the sRGB colour space, not linearised light. This
    is exactly why greying is not contrast-neutral and why these values are
    measured rather than assumed.
    """
    luma = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    return (luma, luma, luma)


def _declarations(source: str, opener: str) -> dict[str, tuple[int, int, int]]:
    """Read every ``--color-*: rgb(...)`` out of one top-level block.

    The opener is matched at the start of a line: these block names also appear in
    prose inside comments, and a substring search finds those first.
    """
    match = re.search(rf"^{re.escape(opener)}\s*\{{", source, re.MULTILINE)
    assert match, f"{opener} block not found"
    end = source.index("\n}", match.end())
    found = {
        name: (int(red), int(green), int(blue))
        for name, red, green, blue in re.findall(
            r"--color-([a-z0-9-]+):\s*rgb\((\d+) (\d+) (\d+)\)", source[match.end() : end]
        )
    }
    assert found, f"no colour declarations inside {opener}"
    return found


@pytest.fixture(scope="module")
def stylesheet() -> str:
    return STYLESHEET.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dark(stylesheet: str) -> dict[str, tuple[int, int, int]]:
    return _declarations(stylesheet, "@theme")


@pytest.fixture(scope="module")
def light(stylesheet: str) -> dict[str, tuple[int, int, int]]:
    return _declarations(stylesheet, ":root.light")


def badge_recipe(variant: str) -> tuple[str, str, float]:
    """What ``c-badges.<variant>`` actually paints: its ink, tint token and strength.

    Read out of the component rather than restated here, so restyling a badge
    moves this check with it instead of leaving it pinned to a pair nothing
    renders. That is not a tidiness point: the secondary badge was checked as
    ``--color-text-secondary`` over the bare row surface, while it ships
    ``--color-text-muted`` over a 30% ``--color-border`` tint -- a different
    foreground over a different background, so the real badge could fall under
    AA with this file green.

    Returns ``(ink token, tint token, tint strength)``, each without the
    ``--color-`` prefix, matching the keys ``_declarations`` yields.
    """
    body = (COMPONENTS / "badges" / f"{variant}.html").read_text(encoding="utf-8")

    ink = re.search(r"\btext-(?!\[)([a-z0-9-]+)", body)
    assert ink, f"c-badges.{variant} names no text colour"

    # ``in_oklab``: Tailwind arbitrary values carry underscores for spaces.
    tint = re.search(r"bg-\[color-mix\(in[ _]oklab,var\(--color-([a-z0-9-]+)\)_(\d+)%", body)
    assert tint, f"c-badges.{variant} no longer paints a mixed tint"

    return ink.group(1), tint.group(1), int(tint.group(2)) / 100


def secondary_button_recipe() -> tuple[str, str, str]:
    """``c-buttons.secondary``: its ink, and its opaque background at rest and on hover.

    Read out of the component for the same reason ``badge_recipe`` is. This
    one matters more than it looks: the button paints an **opaque**
    background, unlike the badges' translucent tints and unlike the row
    itself, and it does so *inside* the filtered subtree -- so its background
    is greyed along with its text, which is a third compositing case.
    """
    body = (COMPONENTS / "buttons" / "secondary.html").read_text(encoding="utf-8")

    ink = re.search(r"\btext-(?!\[)([a-z0-9-]+)", body)
    rest = re.search(r"(?<!hover:)\bbg-(?!\[)([a-z0-9-]+)", body)
    hover = re.search(r"\bhover:bg-(?!\[)([a-z0-9-]+)", body)
    assert ink and rest and hover, "c-buttons.secondary no longer names ink and both backgrounds"

    return ink.group(1), rest.group(1), hover.group(1)


#: How an element's background is produced, which decides what the filter does
#: to it. Three cases, and the row has all three.
TRANSPARENT = "transparent"  # no background: the unfiltered card surface shows through
TINT = "tint"  # a translucent layer inside the filter, over that surface
OPAQUE = "opaque"  # the element's own solid background, inside the filter


def row_foregrounds(
    theme: dict[str, tuple[int, int, int]],
) -> dict[str, tuple[tuple, str, tuple | None, float]]:
    """Every foreground the row greys, and how its background is produced.

    A plan-restricted plugin row is the production case: the title, the
    description explaining the restriction, the badges, and the button that
    resolves it.

    Returned as a spec rather than a finished pair, because the filter changes
    *where* the compositing happens and the tests below need to build the pair
    differently -- see ``pair_for``.
    """

    def badge(variant: str) -> tuple[tuple, str, tuple, float]:
        ink, tint_token, strength = badge_recipe(variant)
        return theme[ink], TINT, theme[tint_token], strength

    cta_ink, cta_rest, cta_hover = secondary_button_recipe()

    return {
        # The plan-required badge. `c-badges.warning` is warning ink over a
        # warning tint.
        "plan-required badge on its own tint": badge("warning"),
        # Muted ink over a border tint, not text-secondary over the surface:
        # the version, artifact-type and count badges all render this.
        "secondary badge on its own tint": badge("secondary"),
        # The Beta badge, which the gated Dependency Track row renders.
        "beta badge on its own tint": badge("info"),
        # Text directly on the row, which paints nothing of its own.
        "restriction description": (theme["text-muted"], TRANSPARENT, None, 0.0),
        "row title": (theme["text"], TRANSPARENT, None, 0.0),
        # The CTA is not text on the row: `c-buttons.secondary` paints an
        # opaque background, inside the filtered subtree, so that background
        # is greyed too. Both of its states are checked -- a hover token can
        # move on its own.
        "upgrade CTA at rest": (theme[cta_ink], OPAQUE, theme[cta_rest], 0.0),
        "upgrade CTA on hover": (theme[cta_ink], OPAQUE, theme[cta_hover], 0.0),
    }


def pair_for(
    ink: tuple,
    kind: str,
    layer: tuple | None,
    alpha: float,
    surface: tuple,
    *,
    filtered: bool,
) -> tuple[tuple, tuple]:
    """The foreground/background pair a browser actually renders.

    The compositing order is the whole point here, and getting it wrong is
    what this function exists to stop. ``filter`` rasterises the row's subtree
    and *then* composites the result onto what is behind it, so what the
    filter touches depends on which side of that boundary the background is:

    ``TRANSPARENT`` -- the row paints no background of its own. Its only
    ``bg-`` rules are hover/checked tints and the disabled variant sets
    ``hover:bg-transparent``, so the card's ``--color-surface`` is an
    *ancestor*, outside the filtered element, and is never greyed.

    ``TINT`` -- a badge's translucent layer is inside the filter, and
    composites onto that unfiltered surface: ``over(greyed(tint), surface,
    alpha)``, not ``greyed(over(tint, surface, alpha))``.

    ``OPAQUE`` -- the CTA paints its own solid ``bg-surface`` inside the
    filter, so nothing shows through and the background is simply
    ``greyed(own_background)``. Treating it as text on the row compared
    filtered ink against an unfiltered surface, which is neither of the two
    things on screen.

    The three differ by little on today's palette, which is why this went
    unnoticed; they do not differ by little once a surface or hover token
    moves, and a guard that reports the wrong ratio then is worse than none.
    """
    foreground = greyed(ink) if filtered else ink

    if kind == TRANSPARENT:
        return foreground, surface

    assert layer is not None, f"{kind} needs a background colour"

    if kind == OPAQUE:
        return foreground, (greyed(layer) if filtered else layer)

    if kind == TINT:
        painted = greyed(layer) if filtered else layer
        return foreground, over(painted, surface, alpha)

    raise AssertionError(f"unknown background kind {kind!r}")


@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_a_greyed_row_keeps_every_foreground_above_aa(request, theme_name: str) -> None:
    theme = request.getfixturevalue(theme_name)
    surface = theme["surface"]
    for label, (ink, kind, layer, alpha) in row_foregrounds(theme).items():
        foreground, background = pair_for(ink, kind, layer, alpha, surface, filtered=True)
        ratio = contrast(foreground, background)
        assert ratio >= SMALL_TEXT, f"{theme_name}: {label} is {ratio:.2f}:1 once greyed, under {SMALL_TEXT}:1"


@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_greying_is_not_what_makes_the_row_readable(request, theme_name: str) -> None:
    """The row must be readable before the filter too.

    Greying can lift a ratio, so a palette that only passes *because* it was
    greyed would hide a failure from every undisabled row painting the same
    tokens.
    """
    theme = request.getfixturevalue(theme_name)
    surface = theme["surface"]
    for label, (ink, kind, layer, alpha) in row_foregrounds(theme).items():
        foreground, background = pair_for(ink, kind, layer, alpha, surface, filtered=False)
        ratio = contrast(foreground, background)
        assert ratio >= SMALL_TEXT, f"{theme_name}: {label} is {ratio:.2f}:1 unfiltered, under {SMALL_TEXT}:1"


def test_the_surface_behind_the_row_is_not_greyed() -> None:
    """The compositing order, pinned as itself.

    Both orders agree whenever the surface is achromatic, because ``greyed``
    and ``over`` are both linear in the channels: greying a mix of a tint and
    a *grey* surface is the same as mixing the greyed tint into it. The light
    surface is pure white, so nothing in the light theme can tell them apart
    -- which is exactly why the wrong order went unnoticed.

    The dark surface is not achromatic, so this uses a hued surface to assert
    the thing that actually differs.
    """
    surface = (30, 33, 50)  # the dark theme's --color-surface: navy, not grey
    tint = (200, 120, 20)
    ink = (240, 200, 120)
    alpha = 0.12

    _, correct = pair_for(ink, TINT, tint, alpha, surface, filtered=True)
    wrong = greyed(over(tint, surface, alpha))

    # What a browser does: grey the translucent tint inside the filter, then
    # lay it over the surface the filter never touched.
    expected = tuple(alpha * greyed(tint)[index] + (1 - alpha) * surface[index] for index in range(3))
    assert all(abs(got - want) < 1e-9 for got, want in zip(correct, expected))

    # The wrong order flattens the surface's hue into grey, so the rendered
    # background keeps a blue cast that the old model did not.
    assert len(set(round(channel, 6) for channel in correct)) > 1, correct
    assert len(set(round(channel, 6) for channel in wrong)) == 1, wrong
    assert correct != wrong


def test_an_achromatic_surface_hides_the_difference() -> None:
    """Why this was invisible: on white, the two orders are identical.

    Kept as a test rather than a comment so the reasoning cannot quietly stop
    being true -- if ``greyed`` ever stops being linear, this fails and the
    test above stops being the only place the order matters.
    """
    tint = (200, 120, 20)
    ink = (120, 70, 10)
    alpha = 0.12

    for surface in ((255, 255, 255), (0, 0, 0), (128, 128, 128)):
        _, correct = pair_for(ink, TINT, tint, alpha, surface, filtered=True)
        wrong = greyed(over(tint, surface, alpha))
        assert all(abs(a - b) < 1e-9 for a, b in zip(correct, wrong)), surface


def test_plain_text_is_measured_against_the_unfiltered_surface() -> None:
    """No tint means no compositing: the background is the surface as painted."""
    surface = (30, 33, 50)
    ink = (200, 200, 210)

    foreground, background = pair_for(ink, TRANSPARENT, None, 0.0, surface, filtered=True)

    assert background == surface, "the ancestor surface must not be greyed"
    assert foreground == greyed(ink), "the text itself is inside the filter"


def test_an_opaque_background_inside_the_filter_is_greyed() -> None:
    """The CTA case: nothing shows through, so the filter owns the background.

    Comparing filtered ink against the unfiltered card surface -- which is
    what treating it as text on the row did -- measures neither of the two
    colours actually on screen.
    """
    surface = (30, 33, 50)
    own_background = (37, 41, 63)
    ink = (255, 255, 255)

    _, background = pair_for(ink, OPAQUE, own_background, 0.0, surface, filtered=True)

    assert background == greyed(own_background)
    assert background != own_background, "an opaque background inside the filter is greyed"
    assert background != surface, "and it is not the card surface either"


def test_both_cta_states_are_covered() -> None:
    """A hover token can move without the rest token moving."""
    ink, rest, hover = secondary_button_recipe()

    assert (ink, rest, hover) == ("text", "surface", "surface-elevated")

    labels = row_foregrounds(_declarations(STYLESHEET.read_text(encoding="utf-8"), "@theme"))
    assert "upgrade CTA at rest" in labels
    assert "upgrade CTA on hover" in labels
    assert all(labels[label][1] == OPAQUE for label in labels if "CTA" in label)


def test_the_row_greys_and_never_fades() -> None:
    """``opacity`` is the defect this file exists for; ``grayscale`` is the fix.

    opacity composites the whole subtree against the page and no descendant can
    opt out, so a row carrying the reason it is unavailable cannot use it. The
    ratios above only describe what ships while that stays true.
    """
    markup = SELECT_ROW.read_text(encoding="utf-8")
    row_class = re.search(r'<div class="([^"]*)"', markup)
    assert row_class, "select-row no longer opens with a class attribute"
    classes = row_class.group(1)
    assert "has-[input:disabled]:grayscale" in classes
    assert not re.search(r"(?<![\w-])opacity-\d", classes), classes
