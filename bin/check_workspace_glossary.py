#!/usr/bin/env python
"""Fail when a newly added line reaches for a tenant word the glossary retires.

A thin wrapper: the matching lives in ``sbomify.apps.core.glossary`` so it can
be tested, since the tests container does not mount ``bin/``.

Run with no arguments to check the working tree against the merge base with
master, or pass a base ref.
"""

from __future__ import annotations

import subprocess  # nosec B404
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sbomify.apps.core.glossary import added_offences, format_report  # noqa: E402


def _run(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=False).stdout  # nosec B603


def _merge_base(base: str) -> str:
    for candidate in (base, f"origin/{base}", f"upstream/{base}"):
        found = _run("git", "merge-base", "HEAD", candidate).strip()
        if found:
            return found
    return ""


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "master"
    merge_base = _merge_base(base)
    if not merge_base:
        sys.stdout.write(f"No merge base with {base}; skipping the glossary check.\n")
        return 0

    offences = added_offences(_run("git", "diff", "-U0", merge_base, "--"))
    if not offences:
        sys.stdout.write("No newly added line reaches for a retired tenant word.\n")
        return 0

    sys.stderr.write(format_report(offences))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
