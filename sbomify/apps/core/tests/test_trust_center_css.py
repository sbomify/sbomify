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

from django.conf import settings

TRUST_CENTER_CSS = Path(settings.BASE_DIR) / "sbomify" / "static" / "css" / "trust-center.css"

HEX = re.compile(r"#([0-9a-fA-F]{3,8})\b")

# Both separators CSS Color 4 allows. The legacy form is comma-separated,
# `rgb(22, 120, 80)`; the modern one is space-separated with an optional
# `/ alpha`, `rgb(22 120 80 / 0.5)`. Recognising only commas left the modern
# form -- the syntax tailwind.src.css itself is written in -- free to carry a
# hue straight past this guard, which is the one thing it exists to stop.
#
# A channel may be a number or a percentage, and `rgba(var(--accent-rgb), 0.1)`
# is deliberately not matched: that is a token reference, which is what the
# sheet is supposed to use.
_CHANNEL = r"(\d{1,3}(?:\.\d+)?%?)"
NUMERIC_RGB = re.compile(r"rgba?\(\s*" + _CHANNEL + r"\s*(?:,\s*|\s+)" + _CHANNEL + r"\s*(?:,\s*|\s+)" + _CHANNEL)


def _rgb_channel(value: str) -> int:
    """One rgb() channel as 0-255, whether written as a number or a percentage."""
    if value.endswith("%"):
        return round(float(value[:-1]) * 255 / 100)
    return round(float(value))


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


def test_no_colour_is_written_as_a_literal() -> None:
    """Every hue in the sheet comes from a token, so the ramps cannot fork again."""
    css = TRUST_CENTER_CSS.read_text()
    offenders: list[str] = []

    for number, line in enumerate(css.splitlines(), 1):
        for digits in HEX.findall(line):
            channels = _hex_channels(digits)
            if channels and _has_hue(channels):
                offenders.append(f"{number}: #{digits}")
        for match in NUMERIC_RGB.findall(line):
            channels = (_rgb_channel(match[0]), _rgb_channel(match[1]), _rgb_channel(match[2]))
            if _has_hue(channels):
                offenders.append(f"{number}: rgb{channels}")

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


# The guard's own coverage. The sheet is clean, so a hole in the pattern looks
# exactly like a passing test: these pin that each syntax is actually seen.
def _hues_in(css: str) -> list[tuple[int, int, int]]:
    """Every numeric rgb() with a hue that the guard's pattern finds in ``css``."""
    found = []
    for match in NUMERIC_RGB.findall(css):
        channels = (_rgb_channel(match[0]), _rgb_channel(match[1]), _rgb_channel(match[2]))
        if _has_hue(channels):
            found.append(channels)
    return found


def test_the_guard_sees_a_hue_in_every_rgb_syntax() -> None:
    """Legacy commas, modern spaces, a slash alpha, and percentage channels."""
    for declaration in (
        "color: rgb(22, 120, 80);",
        "color: rgba(22, 120, 80, 0.5);",
        "color: rgb(22 120 80);",
        "color: rgb(22 120 80 / 0.5);",
        "color: rgba(22 120 80 / 50%);",
        "color: rgb(10% 50% 30%);",
    ):
        assert _hues_in(declaration), f"the guard does not see the hue in {declaration!r}"


def test_the_guard_leaves_neutrals_and_token_references_alone() -> None:
    """What the sheet is allowed to say, in both syntaxes."""
    for declaration in (
        "box-shadow: 0 1px 2px rgb(0 0 0 / 0.05);",
        "color: rgb(255, 255, 255);",
        "color: rgb(0% 0% 0%);",
        "background: rgba(var(--accent-color-rgb), 0.1);",
        "background: rgb(var(--brand-color-rgb) / 0.2);",
    ):
        assert not _hues_in(declaration), f"the guard wrongly flags {declaration!r}"
