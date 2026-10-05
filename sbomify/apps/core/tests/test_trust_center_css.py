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
NUMERIC_RGB = re.compile(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})")


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
            channels = (int(match[0]), int(match[1]), int(match[2]))
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
