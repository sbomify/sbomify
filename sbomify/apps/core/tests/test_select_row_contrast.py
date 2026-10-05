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


def greyed_pairs(theme: dict[str, tuple[int, int, int]]) -> dict[str, tuple[tuple, tuple]]:
    """Every foreground the row greys, against what it is greyed against.

    A plan-restricted plugin row is the production case: the title, the
    description explaining the restriction, the badge naming the plan required
    and the button that resolves it. The CTA and the title both paint
    ``--color-text``.
    """
    surface = theme["surface"]

    def badge(variant: str) -> tuple[tuple, tuple]:
        """A badge's own ink over its own tint, composited on the row surface."""
        ink, tint_token, strength = badge_recipe(variant)
        return theme[ink], over(theme[tint_token], surface, strength)

    return {
        # The plan-required badge. `c-badges.warning` is warning ink over a
        # warning tint.
        "plan-required badge on its own tint": badge("warning"),
        "restriction description": (theme["text-muted"], surface),
        "row title and upgrade CTA": (theme["text"], surface),
        # Muted ink over a border tint, not text-secondary over the surface:
        # the version, artifact-type and count badges all render this.
        "secondary badge on its own tint": badge("secondary"),
        # The Beta badge, which the gated Dependency Track row renders and this
        # file previously omitted: info ink over an info tint.
        "beta badge on its own tint": badge("info"),
    }


@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_a_greyed_row_keeps_every_foreground_above_aa(request, theme_name: str) -> None:
    theme = request.getfixturevalue(theme_name)
    for label, (foreground, background) in greyed_pairs(theme).items():
        ratio = contrast(greyed(foreground), greyed(background))
        assert ratio >= SMALL_TEXT, f"{theme_name}: {label} is {ratio:.2f}:1 once greyed, under {SMALL_TEXT}:1"


@pytest.mark.parametrize("theme_name", ["light", "dark"])
def test_greying_is_not_what_makes_the_row_readable(request, theme_name: str) -> None:
    """The row must be readable before the filter too.

    Greying can lift a ratio -- the warning badge gains about 0.35 in light -- so a
    palette that only passes *because* it was greyed would hide a failure from
    every undisabled row painting the same tokens.
    """
    theme = request.getfixturevalue(theme_name)
    for label, (foreground, background) in greyed_pairs(theme).items():
        ratio = contrast(foreground, background)
        assert ratio >= SMALL_TEXT, f"{theme_name}: {label} is {ratio:.2f}:1 unfiltered, under {SMALL_TEXT}:1"


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
