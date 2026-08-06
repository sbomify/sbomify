#!/usr/bin/env python3
"""Check that CI runs every app's tests.

The ``tests`` job in ci-cd.yml runs an explicit allowlist of paths, and its runner
maps pytest's "collected nothing" exit code to success. Between those two, an app
nobody added to the matrix and a matrix path that no longer resolves both look
exactly like a shard that passed. This notices instead.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-cd.yml"
APPS_DIR = REPO_ROOT / "sbomify" / "apps"
# Where pytest finds an app's tests, per the python_files setting in pyproject.toml.
TEST_LOCATIONS = ("tests", "tests.py")


def _test_groups() -> list[dict[str, str]]:
    workflow: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    groups: list[dict[str, str]] = workflow["jobs"]["tests"]["strategy"]["matrix"]["test-group"]
    return groups


def _apps_with_tests() -> list[str]:
    return sorted(
        path.name
        for path in APPS_DIR.iterdir()
        if path.is_dir()
        and not path.name.startswith("_")
        and any((path / location).exists() for location in TEST_LOCATIONS)
    )


def main() -> int:
    groups = _test_groups()
    covered = {group["path"] for group in groups}
    apps = _apps_with_tests()

    # Checking the app prefix alone is not enough: an app with both tests.py and
    # a tests/ directory would pass on a shard covering only one of them, and the
    # other would never run. Each location has to be reachable from some path.
    problems = []
    for app in apps:
        for location in TEST_LOCATIONS:
            relative = f"sbomify/apps/{app}/{location}"
            if not (APPS_DIR / app / location).exists():
                continue
            if not any(relative.startswith(path.rstrip("/")) for path in covered):
                problems.append(f"  {app}: {location} is not run by any shard")
    # A stale path silently collects nothing; a stale ignore silently stops
    # excluding, which is how e2e tests would leak into the Core shard.
    problems += [
        f"  {group['name']}: {key} {value!r} does not exist"
        for group in groups
        for key in ("path", "ignore")
        if (value := group.get(key)) and not (REPO_ROOT / value).exists()
    ]

    if problems:
        sys.stderr.write(
            "CI test matrix is out of step with the apps:\n\n"
            + "\n".join(problems)
            + f"\n\nFix by editing jobs.tests.strategy.matrix.test-group in {WORKFLOW.relative_to(REPO_ROOT)}.\n"
        )
        return 1

    sys.stdout.write(f"CI runs the tests of all {len(apps)} apps across {len(groups)} shards.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
