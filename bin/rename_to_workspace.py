#!/usr/bin/env python3
"""Rewrite team names to workspace names across the tree (#1453).

Run it again after merging master and it renames whatever your branch added:

    uv run python bin/rename_to_workspace.py

Every rule is idempotent. Migrations and ADRs are never touched, and neither is
a line carrying the KEEP marker: the aliases that keep the old names working,
and the tests that pin them.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEP = "rename-to-workspace: keep"
GLOBS = (
    "sbomify/**/*.py",
    "sbomify/**/*.j2",
    "sbomify/**/*.html",
    "sbomify/**/*.txt",
    "sbomify/**/*.json",
    "sbomify/**/*.ts",
    "AGENTS.md",
    "docs/**/*.md",
)
SKIP = ("/migrations/", "docs/adr/", "/node_modules/", "/staticfiles/")


def _teams_url_names() -> str:
    source = (ROOT / "sbomify/apps/teams/urls.py").read_text()
    return "|".join(sorted(set(re.findall(r'name="([a-z_0-9]+)"', source))))


# Appended to by each phase of #1453, in the order they landed.
RULES: list[tuple[re.Pattern[str], str]] = [
    # P2a: the URL namespace, only before a name the workspaces urlconf defines.
    (re.compile(rf"\bteams:(?=(?:{_teams_url_names()})\b)"), "workspaces:"),
    # P2a: the role settings.
    (re.compile(r"\bTEAMS_(SUPPORTED|INVITABLE)_ROLES\b"), r"WORKSPACE_\1_ROLES"),
]


def rewrite(text: str) -> str:
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if KEEP in line:
            continue
        for pattern, replacement in RULES:
            line = pattern.sub(replacement, line)
        lines[i] = line
    return "".join(lines)


def main() -> None:
    changed = 0
    for glob in GLOBS:
        for path in sorted(ROOT.glob(glob)):
            relative = path.relative_to(ROOT).as_posix()
            if any(part in f"/{relative}" for part in SKIP) or not path.is_file():
                continue
            text = path.read_text()
            new = rewrite(text)
            if new != text:
                path.write_text(new)
                changed += 1
                sys.stdout.write(f"{relative}\n")
    sys.stdout.write(f"{changed} files rewritten\n")


if __name__ == "__main__":
    main()
