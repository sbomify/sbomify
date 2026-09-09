"""Every state that suppresses a finding needs its own label on the table.

A suppressed finding takes one branch in the vulnerabilities table, and that
branch decided between "False positive" and "Not affected" alone. `resolved`
therefore read as "Not affected", which says the opposite of what a fixed
finding means, and the arm further down that would have rendered "Fixed" was
unreachable: `resolved` is in `SUPPRESSED_STATES`, so `vex_suppressed` is always
true for it and the first branch wins before that arm is reached.

Checked against the template source rather than a rendered page, because the
defect was a branch that could not be reached rather than one that rendered
wrongly, and a render test passes happily while an unreachable arm rots.
"""

from __future__ import annotations

import re
from pathlib import Path

from sbomify.apps.vulnerability_scanning.vex import SUPPRESSED_STATES

TEMPLATE = (
    Path(__file__).resolve().parents[1] / "templates" / "core" / "components" / "component_vulnerabilities.html.j2"
)


def _split_at_outer_elif(source: str) -> tuple[str, str]:
    """The suppressed branch, and everything after it in the same if.

    Split on indentation rather than on the first ``elif``: the suppressed
    branch contains its own nested ``elif``, and matching that one is what made
    the first version of this test read the wrong block.
    """
    lines = source.splitlines(keepends=True)
    # The tag on a line of its own. The same condition also appears inline
    # twice, toggling a strikethrough class, and those are not branches.
    start = next(i for i, ln in enumerate(lines) if ln.strip() == "{% if vuln.vex_suppressed %}")
    indent = len(lines[start]) - len(lines[start].lstrip())
    for i in range(start + 1, len(lines)):
        stripped = lines[i].lstrip()
        if stripped.startswith(("{% elif", "{% else", "{% endif")) and (len(lines[i]) - len(stripped) == indent):
            return "".join(lines[start:i]), "".join(lines[i:])
    raise AssertionError("the if block never closes at its own indentation")


def _suppressed_branch(source: str) -> str:
    """The block that renders a finding something has already suppressed."""
    return _split_at_outer_elif(source)[0]


def test_every_suppressing_state_has_its_own_label():
    """Sharing a label between two states is how `resolved` read as unaffected."""
    branch = _suppressed_branch(TEMPLATE.read_text())
    named = set(re.findall(r"vuln\.vex_state == '([a-z_]+)'", branch))

    # One state may be the else default; the rest must be named explicitly.
    unnamed = SUPPRESSED_STATES - named
    assert len(unnamed) <= 1, f"these states share the default label: {sorted(unnamed)}"


def test_a_fixed_finding_does_not_read_as_unaffected():
    branch = _suppressed_branch(TEMPLATE.read_text())
    resolved_arm = re.search(r"vuln\.vex_state == 'resolved' %\}\s*([^\{]+)", branch)
    assert resolved_arm, "resolved has no arm in the suppressed branch"
    assert resolved_arm.group(1).strip() == "Fixed"


def test_the_template_keeps_no_unreachable_state_arm():
    """An arm outside the suppressed branch can never see a suppressing state."""
    after = _split_at_outer_elif(TEMPLATE.read_text())[1]
    outside = set(re.findall(r"vuln\.vex_state == '([a-z_]+)'", after))

    assert not (outside & SUPPRESSED_STATES), (
        f"unreachable: {sorted(outside & SUPPRESSED_STATES)} always take the suppressed branch"
    )
