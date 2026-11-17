"""Dramatiq middleware: one outage line per task that failed on a backend outage.

A task that raises because Postgres or Redis was unreachable is retried by the
``Retries`` middleware, and that retry is what fixes it. Each attempt in between
used to reach Sentry as its own issue, and the log stream as its own traceback.
This writes the shared outage line instead (``sbomify.backend_outage``), which
the console throttles and which only reaches Sentry, as the sustained-fault
line, if the outage outlasts a window. ``before_send`` drops the per-attempt
events on the same test, and keeps the one for an attempt that has no retry
left, because that message is lost.
"""

from __future__ import annotations

from typing import Any

import dramatiq
from dramatiq.broker import Broker, MessageProxy

from sbomify.backend_outage import report_backend_outage


class BackendOutageMiddleware(dramatiq.Middleware):
    def after_process_message(
        self,
        broker: Broker,
        message: MessageProxy,
        *,
        result: Any | None = None,
        exception: BaseException | None = None,
    ) -> None:
        if exception is not None:
            report_backend_outage(exception, f"task {message.actor_name}")
