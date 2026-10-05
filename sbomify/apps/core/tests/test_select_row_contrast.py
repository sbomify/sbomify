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


def row_foregrounds(theme: dict[str, tuple[int, int, int]]) -> dict[str, tuple[tuple, tuple | None, float]]:
    """Every foreground the row greys, and the tint (if any) it sits on.

    A plan-restricted plugin row is the production case: the title, the
    description explaining the restriction, the badges, and the button that
    resolves it. The CTA and the title both paint ``--color-text``.

    Returned as ``(ink, tint, alpha)`` rather than as a finished pair, because
    the filter changes *where* the compositing happens and the two tests below
    need to build the pair differently -- see ``pair_for``.
    """

    def badge(variant: str) -> tuple[tuple, tuple, float]:
        ink, tint_token, strength = badge_recipe(variant)
        return theme[ink], theme[tint_token], strength

    return {
        # The plan-required badge. `c-badges.warning` is warning ink over a
        # warning tint.
        "plan-required badge on its own tint": badge("warning"),
        "restriction description": (theme["text-muted"], None, 0.0),
        "row title and upgrade CTA": (theme["text"], None, 0.0),
        # Muted ink over a border tint, not text-secondary over the surface:
        # the version, artifact-type and count badges all render this.
        "secondary badge on its own tint": badge("secondary"),
        # The Beta badge, which the gated Dependency Track row renders and this
        # file previously omitted: info ink over an info tint.
        "beta badge on its own tint": badge("info"),
    }


def pair_for(
    ink: tuple,
    tint: tuple | None,
    alpha: float,
    surface: tuple,
    *,
    filtered: bool,
) -> tuple[tuple, tuple]:
    """The foreground/background pair a browser actually renders.

    The compositing order is the whole point here, and getting it wrong is
    what this function exists to stop.

    ``filter`` rasterises the row's subtree and *then* composites the result
    onto what is behind it. The disabled row carries
    ``has-[input:disabled]:grayscale`` and no opaque background of its own --
    its only ``bg-`` rules are hover/checked tints, and the disabled variant
    sets ``hover:bg-transparent`` -- so the ancestor ``--color-surface``
    belongs to the card, outside the filtered element, and is **never**
    greyed.

    So, for a badge: grey the translucent tint, then composite that onto the
    unfiltered surface -- ``over(greyed(tint), surface, alpha)``, not
    ``greyed(over(tint, surface, alpha))``. For plain text there is no tint,
    and the background is the surface exactly as it is painted.

    The two differ by little on today's palette, which is why this went
    unnoticed; they do not differ by little once a surface token moves, and a
    guard that reports the wrong ratio then is worse than none.
    """
    foreground = greyed(ink) if filtered else ink
    if tint is None:
        return foreground, surface
    layer = greyed(tint) if filtered else tint
    return foreground, over(layer, surface, alpha)


@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_a_greyed_row_keeps_every_foreground_above_aa(request, theme_name: str) -> None:
    theme = request.getfixturevalue(theme_name)
    surface = theme["surface"]
    for label, (ink, tint, alpha) in row_foregrounds(theme).items():
        foreground, background = pair_for(ink, tint, alpha, surface, filtered=True)
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
    for label, (ink, tint, alpha) in row_foregrounds(theme).items():
        foreground, background = pair_for(ink, tint, alpha, surface, filtered=False)
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

    _, correct = pair_for(ink, tint, alpha, surface, filtered=True)
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
        _, correct = pair_for(ink, tint, alpha, surface, filtered=True)
        wrong = greyed(over(tint, surface, alpha))
        assert all(abs(a - b) < 1e-9 for a, b in zip(correct, wrong)), surface


def test_plain_text_is_measured_against_the_unfiltered_surface() -> None:
    """No tint means no compositing: the background is the surface as painted."""
    surface = (30, 33, 50)
    ink = (200, 200, 210)

    foreground, background = pair_for(ink, None, 0.0, surface, filtered=True)

    assert background == surface, "the ancestor surface must not be greyed"
    assert foreground == greyed(ink), "the text itself is inside the filter"


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
