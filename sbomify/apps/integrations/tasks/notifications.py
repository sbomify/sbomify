"""Posting notifications, off the request and off the scan.

Every message is a request to someone else's API, so it never runs inside the
transaction that caused it: the producer queues one of these once its own
change has committed (``integrations.events``), and a Slack outage costs a
delayed message rather than a failed scan or a failed submission.

Retries are dramatiq's here, unlike the syncs, because a message that is not
retried is simply lost: there is no next scheduled run to pick it up. Only an
unreachable Slack raises; a refused token or channel is recorded and dropped.
"""

from __future__ import annotations

from typing import Any

import dramatiq

from sbomify.apps.integrations.exceptions import ProviderUnavailable
from sbomify.apps.integrations.models import Integration, NotificationRoute
from sbomify.apps.integrations.services import messages
from sbomify.apps.integrations.services.notifications import active_routes, deliver
from sbomify.apps.vulnerability_scanning.utils import SEVERITY_RANK
from sbomify.logging import getLogger
from sbomify.task_utils import record_task_breadcrumb

logger = getLogger(__name__)

_UNRANKED = len(SEVERITY_RANK)


def _deliver_all(routes: Any, build: Any) -> int:
    """Post to every route, and raise only after trying them all.

    One channel's outage must not keep the others from hearing, and a retry
    re-posting to the routes that already succeeded is the lesser harm: the
    message is the same, and losing it is worse than seeing it twice.
    """
    sent = 0
    unavailable: ProviderUnavailable | None = None
    for route in routes:
        message = build(route)
        if message is None:
            continue
        try:
            if deliver(route, message).ok:
                sent += 1
        except ProviderUnavailable as exc:
            unavailable = exc
    if unavailable is not None:
        raise unavailable
    return sent


@dramatiq.actor(queue_name="integrations", max_retries=3, min_backoff=30_000, time_limit=120_000)
def notify_vex_submission(submission_id: str) -> None:
    from sbomify.apps.vulnerability_scanning.models import VexSubmission

    submission = (
        VexSubmission.objects.filter(id=submission_id).select_related("team", "component", "submitted_by").first()
    )
    # Approved, rejected or withdrawn before the message went out: the queue no
    # longer holds it, so announcing it would send people to an empty queue.
    if submission is None or submission.status != VexSubmission.Status.PENDING:
        return

    message = messages.vex_submission_message(submission)
    routes = active_routes(submission.team_id, NotificationRoute.Event.VEX_SUBMISSIONS)
    sent = _deliver_all(routes, lambda _route: message)
    record_task_breadcrumb("notify_vex_submission", "sent", data={"submission_id": submission_id, "routes": sent})


def _new_rows(component_id: str, advisory_ids: list[str]) -> list[dict[str, Any]]:
    """The newly opened advisories as the component reports them now, worst first.

    Read from the current, unsuppressed finding rows rather than trusted from
    the scan: a VEX the workspace already published may cover a new advisory,
    and that is not news to anyone.
    """
    from sbomify.apps.vulnerability_scanning.models import Finding

    found: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in Finding.objects.filter(
        component_id=component_id,
        is_current=True,
        vex_suppressed=False,
        record__advisory_id__in=advisory_ids,
    ).values(
        "record__advisory_id",
        "record__severity",
        "record__package_name",
        "record__package_version",
        "cvss_score",
        "malicious",
    ):
        severity = (row["record__severity"] or "").lower()
        if row["malicious"]:
            # A malicious package carries no severity of its own and outranks
            # every CVE, so it is never filtered out as unrated.
            severity = "critical"
        key = (row["record__advisory_id"], row["record__package_name"], row["record__package_version"])
        found.setdefault(
            key,
            {
                "advisory_id": row["record__advisory_id"],
                "severity": severity,
                "package": row["record__package_name"],
                "version": row["record__package_version"],
                "cvss_score": row["cvss_score"],
            },
        )
    return messages.sort_worst_first(list(found.values()))


def _at_least(rows: list[dict[str, Any]], min_severity: str) -> list[dict[str, Any]]:
    if min_severity == NotificationRoute.Severity.LOW:
        return rows
    ceiling = SEVERITY_RANK.get(min_severity, SEVERITY_RANK["high"])
    return [row for row in rows if SEVERITY_RANK.get(row["severity"], _UNRANKED) <= ceiling]


@dramatiq.actor(queue_name="integrations", max_retries=3, min_backoff=30_000, time_limit=120_000)
def notify_new_vulnerabilities(component_id: str, advisory_ids: list[str]) -> None:
    from sbomify.apps.core.models import Component

    component = Component.objects.filter(id=component_id).select_related("team").first()
    if component is None or not advisory_ids:
        return
    rows = _new_rows(component_id, advisory_ids)
    if not rows:
        return

    def build(route: NotificationRoute) -> messages.Message | None:
        selected = _at_least(rows, route.min_severity)
        return messages.new_vulnerabilities_message(component, selected) if selected else None

    routes = active_routes(component.team_id, NotificationRoute.Event.NEW_VULNERABILITIES)
    sent = _deliver_all(routes, build)
    record_task_breadcrumb(
        "notify_new_vulnerabilities", "sent", data={"component_id": component_id, "count": len(rows), "routes": sent}
    )


@dramatiq.actor(queue_name="integrations", max_retries=3, min_backoff=60_000, time_limit=300_000)
def send_digest(route_id: str) -> None:
    route = (
        NotificationRoute.objects.filter(id=route_id, event=NotificationRoute.Event.DAILY_DIGEST)
        .select_related("integration", "integration__team")
        .first()
    )
    if route is None or route.integration.status != Integration.Status.CONNECTED:
        return
    _deliver_all([route], lambda _route: messages.digest_message(route.integration.team))


@dramatiq.actor(queue_name="integrations", max_retries=0, time_limit=300_000)
def send_due_digests() -> None:
    """Queue one digest per routed workspace. Each is its own task, so one slow
    workspace's snapshot does not hold up everyone else's morning."""
    queued = 0
    for route_id in NotificationRoute.objects.filter(
        event=NotificationRoute.Event.DAILY_DIGEST,
        integration__status=Integration.Status.CONNECTED,
    ).values_list("id", flat=True):
        send_digest.send(route_id)
        queued += 1
    record_task_breadcrumb("send_due_digests", "queued", data={"count": queued})
    logger.info("Queued %d vulnerability digests", queued)
