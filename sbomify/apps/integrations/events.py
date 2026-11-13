"""The two calls other apps make to say something happened that a channel may want.

Both are safe to call from inside any transaction: nothing is queued until it
commits, so a rolled-back submission or scan never reaches a channel, and the
worker never reads a row that is not there yet. Both check for a route first,
so a workspace with no Slack connection costs one indexed query and no task.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from sbomify.apps.integrations.models import NotificationRoute
from sbomify.apps.integrations.services.notifications import active_routes


def vex_submission_created(submission_id: str, team_id: Any) -> None:
    def _queue() -> None:
        if not active_routes(team_id, NotificationRoute.Event.VEX_SUBMISSIONS).exists():
            return
        from sbomify.apps.integrations.tasks.notifications import notify_vex_submission

        notify_vex_submission.send(submission_id)

    transaction.on_commit(_queue)


def vulnerabilities_opened(component_id: str, team_id: Any, advisory_ids: list[str]) -> None:
    if not advisory_ids:
        return

    def _queue() -> None:
        if not active_routes(team_id, NotificationRoute.Event.NEW_VULNERABILITIES).exists():
            return
        from sbomify.apps.integrations.tasks.notifications import notify_new_vulnerabilities

        notify_new_vulnerabilities.send(str(component_id), sorted(advisory_ids))

    transaction.on_commit(_queue)
