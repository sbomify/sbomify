"""The public Trust Center stylesheet takes its colours from the tokens.

``static/css/trust-center.css`` is hand-written and Tailwind does not scan it,
so nothing stops a literal being typed into it. That is how the severity ramp
forked: the sheet grew its own reds, ambers and blues, and a low-severity
advisory ended up blue on the public list while the same advisory was cyan in
the app. ``test_severity_contrast`` pins what the tokens are worth; this pins
that this sheet keeps asking for them.

The rule is narrow on purpose. A neutral literal is allowed, because white text
on a severity fill is the design and ``#ffffff`` says so more plainly than a
token would. Anything with a hue is a colour decision, and colour decisions
belong in ``assets/css/tailwind.src.css`` where both themes and the contrast
guard can see them.

Only this sheet is covered. The other files under ``static/css/`` still carry
literals by the hundred; they are the wider public-pages migration seam and
shrinking them is its own job, not a reason to leave the Trust Center sheet
unguarded.
"""

import re
from pathlib import Path

import pytest
from django.conf import settings

TRUST_CENTER_CSS = Path(settings.BASE_DIR) / "sbomify" / "static" / "css" / "trust-center.css"

HEX = re.compile(r"#([0-9a-fA-F]{3,8})\b")

# Bare words, for the named-colour check. Matched anywhere on the line rather
# than only in a colour position: a name is only reported if Pillow knows it
# as a colour *and* it has a hue, so `display` or `flex` cannot trip it, and
# scanning the whole line means a colour in a shorthand or a custom property
# is covered too.
IDENTIFIER = re.compile(r"(?<![\w-])[a-zA-Z]{3,}(?![\w-])")

# Both separators CSS Color 4 allows. The legacy form is comma-separated,
# `rgb(22, 120, 80)`; the modern one is space-separated with an optional
# `/ alpha`, `rgb(22 120 80 / 0.5)`. Recognising only commas left the modern
# form -- the syntax tailwind.src.css itself is written in -- free to carry a
# hue straight past this guard, which is the one thing it exists to stop.
#
# A channel is anything CSS reads as one: a <number> in its full grammar, so a
# sign, a leading dot or an exponent (`rgb(.5 120 80)`, `rgb(1e2 120 80)`), a
# percentage, or the modern syntax's `none`. The function name is matched in
# any case, as CSS matches it. `rgba(var(--accent-rgb), 0.1)` is deliberately
# not matched: that is a token reference, which is what the sheet is supposed
# to use.
_CHANNEL = r"([+-]?(?:\d*\.\d+|\d+)(?:e[+-]?\d+)?%?|none)"
NUMERIC_RGB = re.compile(
    r"rgba?\(\s*" + _CHANNEL + r"\s*(?:,\s*|\s+)" + _CHANNEL + r"\s*(?:,\s*|\s+)" + _CHANNEL, re.IGNORECASE
)

# The same three channels parked in a custom property, `--tone-rgb: 22 120 80`,
# which `rgb(var(--tone-rgb))` then turns into a hue through the token form the
# guard allows. Only a declaration of exactly three channels counts: `0 1px 2px`
# is a shadow, not a colour.
CHANNEL_PROPERTY = re.compile(
    r"--[\w-]+\s*:\s*" + _CHANNEL + r"\s*(?:,\s*|\s+)" + _CHANNEL + r"\s*(?:,\s*|\s+)" + _CHANNEL + r"\s*(?:;|\}|$)",
    re.IGNORECASE,
)


def _rgb_channel(value: str) -> int:
    """One rgb() channel as 0-255, whether written as a number, a percentage or ``none``."""
    if value.lower() == "none":
        return 0
    if value.endswith("%"):
        return round(float(value[:-1]) * 255 / 100)
    return round(float(value))


# Colour functions that can carry a hue. Checked by name rather than by
# parsing each one's arguments: the point of this guard is that a hue belongs
# in a token, so the honest rule is that none of these may appear at all. A
# genuinely achromatic value has a plain hex or rgb() spelling, which the two
# checks above already allow.
#
# This list is what the old guard was missing: it knew #hex and rgb() only, so
# `hsl(120 100% 25%)` and `oklch(0.6 0.2 150)` -- both perfectly valid, both a
# hue -- went straight past it.
HUE_FUNCTIONS = ("hsl", "hsla", "hwb", "lab", "lch", "oklab", "oklch", "color-mix", "color")
HUE_FUNCTION = re.compile(r"\b(" + "|".join(HUE_FUNCTIONS) + r")\(", re.IGNORECASE)

# Keywords that are legal in a colour position and name no hue of their own.
# ``color-mix`` is handled above and deliberately not here: the sheet's mixes
# are all ``var(--token)``-based, and one written against a literal should be
# caught.
COLOURLESS_KEYWORDS = frozenset(
    {"transparent", "currentcolor", "inherit", "initial", "unset", "revert", "revert-layer", "none"}
)


def _named_colour_channels(name: str) -> tuple[int, int, int] | None:
    """The RGB of a CSS named colour, or None if ``name`` is not one.

    Read from Pillow's table rather than restated here: it is already a
    dependency and carries all 148 CSS names, so `tomato` cannot be missed
    because nobody thought of it.
    """
    from PIL import ImageColor

    digits = ImageColor.colormap.get(name.lower())
    if not isinstance(digits, str) or not digits.startswith("#"):
        return None
    return _hex_channels(digits[1:])


def without_comments(css: str) -> str:
    """The sheet with every ``/* ... */`` blanked, line numbering preserved.

    The comments in this sheet explain the colour decisions, so they are full
    of the words the checks below look for -- "green where it resolved", "the
    app's violet". Scanning them reports prose as a literal. Newlines are kept
    so a real offender still reports the line it is on.
    """
    out: list[str] = []
    rest = css
    while True:
        start = rest.find("/*")
        if start == -1:
            out.append(rest)
            break
        out.append(rest[:start])
        end = rest.find("*/", start + 2)
        if end == -1:
            out.append("\n" * rest[start:].count("\n"))
            break
        out.append("\n" * rest[start:end].count("\n"))
        rest = rest[end + 2 :]
    return "".join(out)


def _hex_channels(digits: str) -> tuple[int, int, int] | None:
    """The first three channels of a #rgb / #rrggbb / #rrggbbaa literal."""
    if len(digits) in (3, 4):
        digits = "".join(digit * 2 for digit in digits)
    if len(digits) not in (6, 8):
        return None
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)


def _has_hue(channels: tuple[int, int, int]) -> bool:
    """White, black and every grey have equal channels; a colour does not."""
    return len(set(channels)) != 1


def test_the_sheet_this_guard_covers_still_exists() -> None:
    """If the sheet is renamed or retired, fail loudly rather than pass empty."""
    assert TRUST_CENTER_CSS.exists(), "trust-center.css moved; update or retire this guard"
    assert "tc-" in TRUST_CENTER_CSS.read_text(), "trust-center.css no longer holds the tc-* layer"


def _offenders_in(css: str) -> list[str]:
    """Every literal the guard reports in ``css``, as ``line: literal``.

    The one scanner: the sheet's test and the guard's own coverage below both
    call it, so a hole the coverage finds is a hole in the guard itself.
    """
    offenders: list[str] = []
    for number, line in enumerate(without_comments(css).splitlines(), 1):
        for digits in HEX.findall(line):
            channels = _hex_channels(digits)
            if channels and _has_hue(channels):
                offenders.append(f"{number}: #{digits}")
        for match in NUMERIC_RGB.findall(line) + CHANNEL_PROPERTY.findall(line):
            channels = (_rgb_channel(match[0]), _rgb_channel(match[1]), _rgb_channel(match[2]))
            if _has_hue(channels):
                offenders.append(f"{number}: rgb{channels}")
        for function in HUE_FUNCTION.findall(line):
            # color-mix is how the sheet composes tokens, so only a mix that
            # names no token is an offender.
            if function.lower() == "color-mix" and "var(--" in line:
                continue
            offenders.append(f"{number}: {function}()")
        for word in IDENTIFIER.findall(line):
            if word.lower() in COLOURLESS_KEYWORDS:
                continue
            channels = _named_colour_channels(word)
            if channels and _has_hue(channels):
                offenders.append(f"{number}: {word}")
    return offenders


def test_no_colour_is_written_as_a_literal() -> None:
    """Every hue in the sheet comes from a token, so the ramps cannot fork again."""
    offenders = _offenders_in(TRUST_CENTER_CSS.read_text())

    assert not offenders, (
        f"colour literals in trust-center.css; use a var(--color-*) token from tailwind.src.css instead: {offenders}"
    )


def test_the_severity_ramp_is_only_referenced_here_never_redefined() -> None:
    """The sheet may read --color-severity-*; declaring one would fork the ramp."""
    declarations = re.findall(r"(--color-severity-[a-z-]+)\s*:", TRUST_CENTER_CSS.read_text())
    assert not declarations, (
        "trust-center.css declares severity tokens; they belong in tailwind.src.css "
        f"so both themes and test_severity_contrast see them: {sorted(set(declarations))}"
    )


# The guard's own coverage. The sheet is clean, so a hole in the checks looks
# exactly like a passing test: these feed declarations through the same scan
# the real test runs and assert what it does and does not report.
@pytest.mark.parametrize(
    "declaration",
    [
        # Legacy and modern rgb(), the original gap.
        "color: rgb(22, 120, 80);",
        "color: rgba(22, 120, 80, 0.5);",
        "color: rgb(22 120 80);",
        "color: rgb(22 120 80 / 0.5);",
        "color: rgba(22 120 80 / 50%);",
        "color: rgb(10% 50% 30%);",
        # Every CSS <number> spelling, and the function name in any case.
        "color: rgb(.5 120 80);",
        "color: rgb(-1 120 80);",
        "color: rgb(+22 120 80);",
        "color: rgb(1e2 120 80);",
        "color: rgb(22.5e0 120 80);",
        "color: RGB(22 120 80);",
        "color: Rgba(22, 120, 80, 0.5);",
        "color: rgb(none 120 80);",
        # Raw channels parked in a custom property, then read through the
        # token form the guard allows.
        ".tone { --tone-rgb: 22 120 80; color: rgb(var(--tone-rgb)); }",
        "--tone-rgb: 22, 120, 80;",
        "color: #178050;",
        "color: #1785;",
        # The colour functions the guard did not know at all.
        "color: hsl(120 100% 25%);",
        "color: hsl(120, 100%, 25%);",
        "color: hsla(120 100% 25% / 0.5);",
        "color: oklch(0.6 0.2 150);",
        "color: oklab(0.6 -0.1 0.1);",
        "color: lch(50% 40 150);",
        "color: lab(50% -40 30);",
        "color: hwb(120 10% 20%);",
        "color: color(display-p3 0.1 0.5 0.3);",
        "background: color-mix(in oklab, #178050 20%, transparent);",
        # Named colours, which it also did not know.
        "color: red;",
        "color: tomato;",
        "border-color: rebeccapurple;",
        "background: MidnightBlue;",
    ],
)
def test_the_guard_reports_every_way_a_hue_can_be_written(declaration: str) -> None:
    assert _offenders_in(declaration), f"the guard does not see the hue in {declaration!r}"


@pytest.mark.parametrize(
    "declaration",
    [
        # Neutrals: the sheet is allowed to say these.
        "box-shadow: 0 1px 2px rgb(0 0 0 / 0.05);",
        "color: rgb(255, 255, 255);",
        "color: rgb(0% 0% 0%);",
        "--shadow-rgb: 0 0 0;",
        "color: #ffffff;",
        "color: #000;",
        "color: white;",
        "color: black;",
        "color: transparent;",
        "fill: currentColor;",
        "color: inherit;",
        # Token references, which are the whole point of the sheet.
        "background: rgba(var(--accent-color-rgb), 0.1);",
        "background: rgb(var(--brand-color-rgb) / 0.2);",
        "color: var(--color-severity-high);",
        "background: color-mix(in oklab, var(--color-success) 12%, transparent);",
        # Words that are not colours, and property names that merely look it.
        "display: flex;",
        "align-items: center;",
        "transition: color 150ms ease;",
        "font-family: Inter, system-ui, sans-serif;",
    ],
)
def test_the_guard_leaves_neutrals_and_tokens_alone(declaration: str) -> None:
    assert _offenders_in(declaration) == [], f"the guard wrongly flags {declaration!r}"


def test_prose_in_a_comment_is_not_a_literal() -> None:
    """The sheet's comments explain its colour decisions, in those words.

    Three of them name "green" and "violet", so scanning comments reported
    prose as drift -- which is how a guard gets switched off.
    """
    css = """
    /* The dot is green where it resolved, violet for fix_in_progress,
       and #ff0000 would be wrong here. */
    .tc-dot-success { --tone: var(--color-success); }
    """

    assert _offenders_in(css) == []


def test_a_literal_after_a_comment_still_reports_its_line() -> None:
    """Blanking comments must not shift the line numbers in the message."""
    css = "/* a\nmulti-line\ncomment */\ncolor: #178050;\n"

    body = without_comments(css)

    assert body.splitlines()[3].strip() == "color: #178050;"
