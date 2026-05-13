#!/usr/bin/env python
"""Release script for production containers (distroless-compatible, no shell needed).

Runs database migrations and clears the Redis cache as part of the deployment process.

Pre-apply, the script logs the migration plan via ``migrate --plan`` so the
operator can grep the deploy log to see exactly which migrations a release is
about to apply. The plan is informational only — it does not gate the deploy;
if a destructive migration is unexpected, the operator must catch it in the
log review.
"""

import os
import sys

import django


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sbomify.settings")
    django.setup()

    from django.core.management import call_command

    # Log the migration plan BEFORE applying. `--plan` only prints which
    # migrations would run, in order — it doesn't apply anything, so it's
    # safe to run unconditionally. Output goes to stdout, captured by
    # container logs / deploy log aggregation. Operators can grep for
    # "[release] Migration plan:" to find this section in the deploy log.
    sys.stderr.write("[release] Migration plan:\n")
    sys.stderr.flush()
    call_command("migrate", "--plan", "--no-input")

    sys.stderr.write("[release] Applying migrations...\n")
    sys.stderr.flush()
    call_command("migrate", "--no-input")
    sys.stderr.write("[release] Migrations applied successfully.\n")

    from django.core.cache import cache

    try:
        cache.clear()
        sys.stderr.write("[release] Redis cache cleared.\n")
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Warning: Could not clear Redis cache: {e}\n")


if __name__ == "__main__":
    main()
