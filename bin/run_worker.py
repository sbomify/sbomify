#!/usr/bin/env python
"""Launch the dramatiq worker with the cron scheduler in the same container.

The cron scheduler (`manage.py crontab`) is a producer that fires
`actor.send()` calls into Redis at scheduled times. The worker
(`manage.py rundramatiq`) is the consumer. They communicate only through
Redis, so they don't need to share a process — but co-locating them in
one container avoids running a separate scheduler service.

Single-leader semantics are enforced by `dramatiq-crontab`'s Redis lock
(see `DRAMATIQ_CRONTAB.REDIS_URL` in settings.py). Every worker replica
spawns a scheduler subprocess; only one acquires the lock and runs the
scheduler. The others exit the subprocess immediately and run as
worker-only.
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> None:
    # Spawn scheduler as a child subprocess. Stdout/stderr inherit so its
    # logs surface in the container's log stream alongside the worker's.
    subprocess.Popen([sys.executable, "manage.py", "crontab"])

    # Replace the current process with rundramatiq so it becomes PID 1
    # and receives container signals directly. The scheduler subprocess
    # is reaped by the kernel when the container exits.
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "manage.py",
            "rundramatiq",
            "-p",
            os.environ.get("DRAMATIQ_PROCESSES", "1"),
            "-t",
            os.environ.get("DRAMATIQ_THREADS", "4"),
        ],
    )


if __name__ == "__main__":
    main()
