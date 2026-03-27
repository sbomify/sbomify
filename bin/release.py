#!/usr/bin/env python
"""Release script for production containers (distroless-compatible, no shell needed).

Runs database migrations and clears the Redis cache as part of the deployment process.
"""

import os
import sys

import django


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "sbomify.settings")
    django.setup()

    from django.core.management import call_command

    call_command("migrate", "--noinput")

    from django.core.cache import cache

    try:
        cache.clear()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Warning: Could not clear Redis cache: {e}\n")


if __name__ == "__main__":
    main()
