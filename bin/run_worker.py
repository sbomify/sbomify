#!/usr/bin/env python
"""Launch the dramatiq worker with the cron scheduler in the same container.

The cron scheduler (`manage.py crontab`) is a producer that fires
`actor.send()` calls into Redis at scheduled times. The worker
(`manage.py rundramatiq`) is the consumer. They communicate only through
Redis; co-locating them avoids running a separate scheduler service.

Single-leader scheduling across replicas is enforced by `dramatiq-crontab`'s
Redis lock (`DRAMATIQ_CRONTAB.REDIS_URL` in settings.py). Every worker
replica spawns a scheduler subprocess via this launcher; only one acquires
the lock and runs the scheduler — the others exit cleanly with "Another
scheduler is already running." and continue as worker-only.

Any extra CLI args passed to this launcher are forwarded to `rundramatiq`,
so concurrency flags (`-p`/`-t`) stay configurable from docker-compose.
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> None:
    # Fire-and-forget the scheduler. Its stdout/stderr inherit, so logs
    # appear in the same container log stream as the worker's.
    subprocess.Popen([sys.executable, "manage.py", "crontab"])

    # Replace the current process with rundramatiq so it becomes PID 1
    # and receives container signals directly. The scheduler subprocess
    # is reaped by the kernel when the container exits; the Redis lock's
    # 10s TTL frees it for the next replica to acquire.
    os.execvp(
        sys.executable,
        [sys.executable, "manage.py", "rundramatiq", *sys.argv[1:]],
    )


if __name__ == "__main__":
    main()
