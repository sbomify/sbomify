#!/usr/bin/env python3
"""Check that CI still runs every test exactly once.

The ``tests`` job used to run an explicit allowlist of paths, so the thing worth
checking was whether a new app had been added to it. It now runs pytest over the
whole ``sbomify`` package, which makes that class of hole structurally
impossible — but only for as long as the invocation keeps that shape. And the
``e2e-tests`` job traded one serial job for a pytest-split matrix, which brings a
new way to lose tests silently: if ``--splits`` and the job matrix disagree, the
surplus groups collect nothing (which pytest-split reports as a pass) and the
tests that should have been in them never run at all.

So this checks the two properties the jobs now depend on:

* ``tests`` collects from the package root and excludes only the e2e directory,
* ``e2e-tests`` shards exactly that directory, with ``--splits`` equal to the
  number of matrix groups, and the groups numbered ``1..splits``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-cd.yml"
APPS_DIR = REPO_ROOT / "sbomify" / "apps"
E2E_DIR = "sbomify/apps/core/tests/e2e"
# Where pytest finds an app's tests, per the python_files setting in pyproject.toml.
TEST_LOCATIONS = ("tests", "tests.py")


def _jobs() -> dict[str, Any]:
    jobs: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    return jobs


def _pytest_command(job: dict[str, Any], step_prefix: str) -> str:
    """The `run:` body of the step whose name starts with step_prefix."""
    for step in job["steps"]:
        if step.get("name", "").startswith(step_prefix):
            run: str = step["run"]
            return run
    raise SystemExit(f"no step named {step_prefix!r} in {WORKFLOW.relative_to(REPO_ROOT)}")


def _apps_with_tests() -> list[str]:
    return sorted(
        path.name
        for path in APPS_DIR.iterdir()
        if path.is_dir()
        and not path.name.startswith("_")
        and any((path / location).exists() for location in TEST_LOCATIONS)
    )


def main() -> int:
    jobs = _jobs()
    problems: list[str] = []

    # --- the `tests` job collects every app ------------------------------
    unit = _pytest_command(jobs["tests"], "Run tests")
    # Bare `sbomify` as the target is what makes "a new app is covered
    # automatically" true; an allowlist of paths would silently drop one.
    if not re.search(r"^\s*sbomify\s*(?:\||$)", unit, re.MULTILINE):
        problems.append(
            "  tests: the pytest target is no longer the bare `sbomify` package, "
            "so a newly added app may not be collected"
        )
    ignored = set(re.findall(r"--ignore=(\S+)", unit))
    if ignored != {E2E_DIR}:
        problems.append(f"  tests: expected to ignore exactly {{{E2E_DIR}}}, ignores {ignored or '{}'}")
    if "-eq 5" in unit:
        problems.append("  tests: pytest's 'collected nothing' exit code is being mapped to success again")

    # --- the `e2e-tests` matrix and --splits agree -----------------------
    e2e_job = jobs["e2e-tests"]
    groups = e2e_job["strategy"]["matrix"]["group"]
    e2e = _pytest_command(e2e_job, "Run E2E Tests")

    splits = re.search(r"--splits\s+(\d+)", e2e)
    if not splits:
        problems.append("  e2e-tests: no --splits in the pytest invocation")
    elif int(splits.group(1)) != len(groups):
        problems.append(
            f"  e2e-tests: --splits {splits.group(1)} but {len(groups)} matrix groups — "
            f"{abs(int(splits.group(1)) - len(groups))} group(s) would run the wrong tests or none"
        )
    if sorted(groups) != list(range(1, len(groups) + 1)):
        problems.append(f"  e2e-tests: matrix groups must be 1..{len(groups)}, got {groups}")
    if E2E_DIR not in e2e:
        problems.append(f"  e2e-tests: does not run {E2E_DIR}")

    durations = re.search(r"--durations-path\s+(\S+)", e2e)
    if not durations:
        problems.append("  e2e-tests: no --durations-path, so the shards would split by test count only")
    else:
        path = REPO_ROOT / durations.group(1)
        if not path.exists():
            problems.append(f"  e2e-tests: durations file {durations.group(1)} does not exist")
        else:
            try:
                json.loads(path.read_text())
            except json.JSONDecodeError as exc:
                problems.append(f"  e2e-tests: durations file {durations.group(1)} is not valid JSON ({exc})")

    if problems:
        sys.stderr.write(
            "CI would no longer run every test exactly once:\n\n"
            + "\n".join(problems)
            + f"\n\nFix by editing jobs.tests / jobs.e2e-tests in {WORKFLOW.relative_to(REPO_ROOT)}.\n"
        )
        return 1

    apps = _apps_with_tests()
    sys.stdout.write(
        f"CI collects all {len(apps)} apps' tests in one job and shards {E2E_DIR} across {len(groups)} groups.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
