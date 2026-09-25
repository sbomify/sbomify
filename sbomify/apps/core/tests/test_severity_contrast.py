"""Severity colours must stay readable in both themes.

The severity ramp is declared three ways and each has a different contrast
partner, so a value that looks fine in one place can fail in another:

* ``--color-severity-*`` in ``@theme`` is text over a 12% tint of itself on the
  dark surface.
* the same names under ``:root.light`` are text over that tint on white.
* ``--color-severity-*-fill`` is a solid background that always carries white
  text, in the app and on the public Trust Center. It is declared in the plain
  ``:root`` block rather than in ``@theme``, because its only consumer is
  ``static/css/trust-center.css``, which Tailwind does not scan: an ``@theme``
  variable no scanned source mentions is tree-shaken out of the build, and the
  rules reading it would resolve to transparent.

These ran at 1.53 to 3.81 after the prototype migration reused the dark ramp on
white, so the numbers are pinned here rather than left to a screenshot review.
"""

import re
from pathlib import Path

import pytest

STYLESHEET = Path(__file__).resolve().parents[3] / "assets" / "css" / "tailwind.src.css"
COMPONENTS = Path(__file__).resolve().parents[3] / "templates" / "components"

DARK_SURFACE = (30, 33, 50)
WHITE = (255, 255, 255)

# WCAG 2.1: 4.5 for text below 24px (badges are 12px), 3.0 for large text
# (the 32px trend values) and for the fills' white label.
SMALL_TEXT = 4.5
LARGE_TEXT = 3.0

LEVELS = ("critical", "high", "medium", "low")


def _relative_luminance(rgb: tuple[float, float, float]) -> float:
    channels = []
    for value in rgb:
        srgb = value / 255
        channels.append(srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(foreground: tuple[float, ...], background: tuple[float, ...]) -> float:
    lighter, darker = sorted((_relative_luminance(foreground), _relative_luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def over(colour: tuple[int, ...], surface: tuple[int, ...], tint: float) -> tuple[float, ...]:
    """The tint a badge paints behind its own text."""
    return tuple(tint * colour[i] + (1 - tint) * surface[i] for i in range(3))


def painted_tints() -> set[float]:
    """Every tint strength a component paints behind severity text.

    Read out of the templates rather than hardcoded. c-badges.severity paints
    12% and c-branded.badge paints 14%, and a ramp tuned only for the weaker one
    fails on the stronger. A component added later with a third strength should
    fail here, not on a customer's Trust Center.
    """
    found = set()
    for template in COMPONENTS.rglob("*.html"):
        body = template.read_text(encoding="utf-8")
        for percent in re.findall(r"var\(--color-severity-[a-z]+\)_(\d+)%", body):
            found.add(int(percent) / 100)
        # c-branded.badge routes the token through --tone, so the percentage and
        # the token name are not adjacent in the source.
        if "--tone: " in body and "--color-severity-" in body:
            for percent in re.findall(r"var\(--tone\)_(\d+)%", body):
                found.add(int(percent) / 100)
    # The 20%/32% border strengths come through the same patterns; only the
    # strengths weak enough to sit behind text are a contrast question, and the
    # border ones are always stronger, so they are a lower bound, not a risk.
    assert found, "no severity tint found in the component library"
    return {t for t in found if t <= 0.15}


def _declarations(source: str, opener: str) -> dict[str, tuple[int, int, int]]:
    """Read ``--color-severity-*`` out of one top-level block.

    The opener is matched at the start of a line: both block names also appear
    in prose inside comments, and a substring search finds those first.
    """
    match = re.search(rf"^{re.escape(opener)}\s*\{{", source, re.MULTILINE)
    assert match, f"{opener} block not found"
    end = source.index("\n}", match.end())
    found = {}
    for name, red, green, blue in re.findall(
        r"--color-severity-([a-z-]+):\s*rgb\((\d+) (\d+) (\d+)\)", source[match.end() : end]
    ):
        found[name] = (int(red), int(green), int(blue))
    assert found, f"no severity declarations inside {opener}"
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


@pytest.fixture(scope="module")
def root(stylesheet: str) -> dict[str, tuple[int, int, int]]:
    return _declarations(stylesheet, ":root")


@pytest.mark.parametrize("level", LEVELS)
def test_dark_severity_text_is_readable_on_every_tint_in_use(dark, level: str) -> None:
    colour = dark[level]
    for tint in painted_tints():
        assert contrast(colour, over(colour, DARK_SURFACE, tint)) >= SMALL_TEXT, tint
    assert contrast(colour, DARK_SURFACE) >= LARGE_TEXT


@pytest.mark.parametrize("level", LEVELS)
def test_light_severity_text_is_readable_on_every_tint_in_use(light, level: str) -> None:
    colour = light[level]
    for tint in painted_tints():
        assert contrast(colour, over(colour, WHITE, tint)) >= SMALL_TEXT, tint
    assert contrast(colour, WHITE) >= LARGE_TEXT


def test_the_fill_ramp_survives_greyscale(root) -> None:
    """Some fills carry no text of their own: a CVSS chip on an advisory with no
    score prints a dash, and the row spine is aria-hidden. Colour is the only
    signal there, so the ramp must separate by lightness too, or high and medium
    are one colour to a red-green colour-blind reader and on a printed page."""
    ordered = ["critical-fill", "high-fill", "medium-fill", "low-fill", "none-fill"]
    luminances = [_relative_luminance(root[name]) for name in ordered]
    assert luminances == sorted(luminances), "fill lightness must run with severity"
    for first, second in zip(ordered, ordered[1:]):
        assert contrast(root[first], root[second]) >= 1.2, f"{first} and {second} are too close"


@pytest.mark.parametrize("level", LEVELS)
def test_each_level_has_a_distinct_light_value(light, dark, level: str) -> None:
    """The light ramp is retuned, not copied from dark as it was before."""
    assert light[level] != dark[level]


@pytest.mark.parametrize("level", (*LEVELS, "none"))
def test_fills_carry_white_text(root, level: str) -> None:
    assert contrast(root[f"{level}-fill"], WHITE) >= SMALL_TEXT


def test_fills_are_theme_independent(light) -> None:
    """Fills sit under white text in both themes, so :root.light must not
    shadow them with a second value that could drift."""
    assert not [name for name in light if name.endswith("-fill")]


def test_fills_are_declared_where_the_build_will_emit_them(dark, root) -> None:
    """Tailwind tree-shakes an @theme variable that no scanned source mentions.

    trust-center.css is plain static CSS, outside Tailwind's source scanning, so
    a fill declared in @theme is dropped from the build and every rule reading it
    falls back to transparent: the CVSS chip turns white-on-white and the facet
    dots disappear. The plain :root block is emitted verbatim, so that is where
    these belong.
    """
    assert not [name for name in dark if name.endswith("-fill")], (
        "severity fills must not live in @theme; trust-center.css is not scanned by Tailwind"
    )
    assert sorted(name for name in root if name.endswith("-fill")) == [
        "critical-fill",
        "high-fill",
        "low-fill",
        "medium-fill",
        "none-fill",
    ]
