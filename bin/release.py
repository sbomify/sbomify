#!/usr/bin/env python
"""Release script for production containers (distroless-compatible, no shell needed).

This is the Python equivalent of release.sh for use in Chainguard distroless
containers where /bin/sh is not available.
"""

import logging
import subprocess
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Starting release process...")

    # Step 1: Run migrations
    logger.info("Running migrations...")
    result = subprocess.run(
        [sys.executable, "manage.py", "migrate", "--noinput"],
        check=False,
    )
    if result.returncode != 0:
        logger.error("Failed to run migrations")
        sys.exit(1)

    # Step 2: Clear Redis cache
    logger.info("Clearing Redis cache...")
    result = subprocess.run(
        [
            sys.executable,
            "manage.py",
            "shell",
            "-c",
            (
                "from django.core.cache import cache\n"
                "try:\n"
                "    cache.clear()\n"
                "    print('Redis cache cleared successfully')\n"
                "except Exception as e:\n"
                "    print(f'Warning: Could not clear Redis cache: {e}')\n"
            ),
        ],
        check=False,
    )
    if result.returncode != 0:
        logger.warning("Redis cache clearing failed, continuing deployment...")

    logger.info("Release process completed successfully")


if __name__ == "__main__":
    main()
