"""The tenant words the glossary retires, and how to spot new ones.

AGENTS.md settles that the tenant is a *workspace*. The tree does not agree
yet: ``team_key`` appears about 1200 times and ``current_team`` about 370, and
retiring them touches models, sessions and the database. Rewriting them today
would be an enormous diff with no user value.

So the gate reads a diff, not the tree. Existing occurrences are left alone and
only newly added lines are rejected, which lets the count fall as files are
touched instead of climbing while the rename waits its turn.

The logic lives here rather than in ``bin/`` because the tests container does
not mount that directory; the script there is a thin wrapper around this.
"""

from __future__ import annotations

import re

#: Identifiers the glossary retires, and what to reach for instead.
#: Deliberately narrow: ``team`` alone is too common to gate on, and the ``Team``
#: model is TID251's job once the P3 alias exists.
RETIRED: dict[str, str] = {
    "team_key": "workspace_key",
    "current_team": "current_workspace",
    "user_teams": "user_workspaces",
    "token_team": "token_workspace",  # nosec B105 - a request-attribute name, not a credential
}

#: The teams app owns the model and may say team as much as it likes.
EXEMPT_PREFIXES = ("sbomify/apps/teams/",)
#: Migrations are frozen history. Tests follow whatever they are testing.
EXEMPT_PARTS = ("/migrations/", "/tests/", "check_workspace_glossary.py", "core/glossary.py")

_DIFF_HEADER = re.compile(r"^\+\+\+ b/(.+)$")


def is_exempt(path: str) -> bool:
    return path.startswith(EXEMPT_PREFIXES) or any(part in path for part in EXEMPT_PARTS)


def added_offences(diff: str) -> list[tuple[str, str, str]]:
    """Return ``(path, retired word, added line)`` for each offending addition.

    Only ``+`` lines count. Removing a retired word is the point of the exercise,
    not a violation of it.
    """
    offences: list[tuple[str, str, str]] = []
    path = ""
    for line in diff.splitlines():
        header = _DIFF_HEADER.match(line)
        if header:
            path = header.group(1)
            continue
        if not line.startswith("+") or line.startswith("+++") or not path or is_exempt(path):
            continue
        for word in RETIRED:
            # Word boundaries, so workspace_key does not trip on the team_key
            # inside it.
            if re.search(rf"\b{word}\b", line):
                offences.append((path, word, line[1:].strip()))
    return offences


def format_report(offences: list[tuple[str, str, str]]) -> str:
    detail = "\n".join(f"  {path}\n    {word} -> {RETIRED[word]}\n    {line[:100]}\n" for path, word, line in offences)
    return (
        "New code is using tenant words the glossary retired (see AGENTS.md):\n\n"
        + detail
        + "\nExisting occurrences are fine. This rejects only newly added lines,\n"
        "so the count falls as files are touched rather than climbing.\n"
    )
