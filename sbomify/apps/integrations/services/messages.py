"""What each notification says, as Slack Block Kit.

Every message is laid out the same way, so a channel learns to read them at a
glance: a header naming what happened, the facts as a two-column field grid,
the detail as a list with a severity marker per line, then a context line
(workspace and time) and the buttons that open the page to act on it.

Every message also carries a plain ``text``. Slack shows it in the desktop
notification and reads it to screen readers, so it has to stand on its own.

Anything a workspace or a scanner wrote (a component name, a package, an
agent's context) goes through ``_escape``: Slack reads ``<`` and ``>`` as link
and mention syntax, so an unescaped ``<!channel>`` in a component name would
ping a whole channel. Header blocks are ``plain_text`` and need no escaping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from django.urls import reverse
from django.utils import timezone

from sbomify.apps.core.url_utils import get_base_url
from sbomify.apps.security_advisories.references import advisory_url
from sbomify.apps.vulnerability_scanning.utils import SEVERITY_RANK

if TYPE_CHECKING:
    from sbomify.apps.teams.models import Workspace
    from sbomify.apps.vulnerability_scanning.models import VexSubmission

# Slack refuses a section over 3000 characters, a header over 150 and a
# message over 50 blocks, and a channel stops reading long before any of them.
MAX_LISTED = 10
MAX_CONTEXT_CHARS = 300
MAX_HEADER_CHARS = 150
MAX_ADVISORIES_NAMED = 5

_SEVERITY_LABELS = ("critical", "high", "medium", "low")

# One marker per severity, the same in every message, so a list can be scanned
# by colour before it is read. The words stay beside them: the colour is a
# shortcut, not the information.
SEVERITY_EMOJI = {
    "critical": ":red_circle:",
    "high": ":large_orange_circle:",
    "medium": ":large_yellow_circle:",
    "low": ":large_blue_circle:",
}
UNRATED_EMOJI = ":white_circle:"


@dataclass(frozen=True)
class Message:
    text: str
    blocks: list[dict[str, Any]]


def _escape(value: Any) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _absolute(path: str) -> str:
    return f"{get_base_url().rstrip('/')}{path}"


def _link(url: str, label: str) -> str:
    return f"<{url}|{_escape(label)}>" if url else _escape(label)


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def _header(text: str) -> dict[str, Any]:
    if len(text) > MAX_HEADER_CHARS:
        text = text[: MAX_HEADER_CHARS - 1].rstrip() + "…"
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _fields(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """A two-column grid of labelled facts. Slack allows ten fields per section."""
    return {
        "type": "section",
        "fields": [{"type": "mrkdwn", "text": f"*{label}*\n{value}"} for label, value in pairs[:10]],
    }


def _divider() -> dict[str, Any]:
    return {"type": "divider"}


def _slack_date(moment: datetime) -> str:
    """A time Slack renders in each reader's own timezone, with a UTC fallback."""
    fallback = moment.strftime("%Y-%m-%d %H:%M UTC")
    return f"<!date^{int(moment.timestamp())}^{{date_short_pretty}} at {{time}}|{fallback}>"


def _context(team: Workspace, moment: datetime | None = None) -> dict[str, Any]:
    moment = moment or timezone.now()
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f":shield: sbomify · {_escape(team.name)} · {_slack_date(moment)}"}],
    }


def _buttons(*buttons: tuple[str, str, str]) -> dict[str, Any]:
    """``(label, url, style)``; the first is usually ``primary``, ``""`` is the neutral default."""
    elements = []
    for label, url, style in buttons:
        element: dict[str, Any] = {"type": "button", "text": {"type": "plain_text", "text": label}, "url": url}
        if style:
            element["style"] = style
        elements.append(element)
    return {"type": "actions", "elements": elements}


def severity_emoji(severity: str) -> str:
    return SEVERITY_EMOJI.get(severity, UNRATED_EMOJI)


def _severity_counts(severities: list[str]) -> str:
    """``:red_circle: 1 critical  :large_orange_circle: 2 high``, worst first, zeros left out."""
    counts = {label: 0 for label in _SEVERITY_LABELS}
    other = 0
    for severity in severities:
        if severity in counts:
            counts[severity] += 1
        else:
            other += 1
    parts = [f"{SEVERITY_EMOJI[label]} {count} {label}" for label, count in counts.items() if count]
    if other:
        parts.append(f"{UNRATED_EMOJI} {other} unrated")
    return "   ".join(parts)


def _vulnerability_line(advisory_id: str, severity: str, package: str = "", version: str = "", where: str = "") -> str:
    """``:red_circle: *CVE-2024-1234* critical · `pkg@1.0` · Component``, the id linked to its advisory."""
    marker = severity_emoji(severity)
    parts = [f"{marker} *{_link(advisory_url(advisory_id), advisory_id)}* {_escape(severity or 'unrated')}"]
    if package:
        parts.append(f"`{_escape(package)}{'@' + _escape(version) if version else ''}`")
    if where:
        parts.append(_escape(where))
    return " · ".join(parts)


def connection_test_message(team: Workspace, label: str) -> Message:
    text = f"sbomify is connected. {label} for {team.name} will be posted here."
    return Message(
        text=text,
        blocks=[
            _header(":white_check_mark: sbomify is connected"),
            _section(f"*{_escape(label)}* for *{_escape(team.name)}* will be posted in this channel."),
            _context(team),
        ],
    )


def vex_submission_message(submission: VexSubmission) -> Message:
    component = submission.component
    team = submission.team
    review_url = _absolute(reverse("vulnerability_scanning:vulnerability_scans", args=[team.key])) + "?view=review"
    component_url = _absolute(reverse("core:component_details", kwargs={"component_id": component.id}))

    if submission.kind == submission.Kind.DOCUMENT:
        what = "A VEX document"
        size = "Document"
    else:
        count = len(submission.decisions or [])
        what = _plural(count, "VEX ruling")
        size = _plural(count, "ruling")

    advisories = list(submission.advisory_ids or [])
    covering = ", ".join(_link(advisory_url(advisory), advisory) for advisory in advisories[:MAX_ADVISORIES_NAMED])
    if len(advisories) > MAX_ADVISORIES_NAMED:
        covering += f" and {len(advisories) - MAX_ADVISORIES_NAMED} more"

    if submission.submitted_by is not None:
        who = submission.submitted_by.get_full_name() or submission.submitted_by.username
    elif submission.submitted_token_description:
        who = f"Access token “{submission.submitted_token_description}”"
    else:
        who = "An access token"

    fields = [
        ("Component", _link(component_url, component.name)),
        ("Submitted by", _escape(who)),
        ("Contains", size),
    ]
    if covering:
        fields.append(("Covers", covering))

    blocks: list[dict[str, Any]] = [
        _header(":inbox_tray: VEX ruling waiting for approval"),
        _section(f"{_escape(what)} for *{_link(component_url, component.name)}* needs a reviewer."),
        _fields(fields),
    ]
    context = (submission.context or "").strip()
    if context:
        if len(context) > MAX_CONTEXT_CHARS:
            context = context[:MAX_CONTEXT_CHARS].rstrip() + "…"
        blocks.append(_section("*Context*\n" + "\n".join(f"> {_escape(line)}" for line in context.splitlines())))
    blocks += [
        _context(team, submission.submitted_at),
        _buttons(("Review", review_url, "primary"), ("View component", component_url, "")),
    ]
    return Message(text=f"{what} for {component.name} is waiting for approval.", blocks=blocks)


def new_vulnerabilities_message(component: Any, rows: list[dict[str, Any]]) -> Message:
    """``rows`` are ``advisory_id``, ``severity``, ``package``, ``version``, worst first."""
    component_url = _absolute(reverse("core:component_details", kwargs={"component_id": component.id}))
    vulnerabilities_url = _absolute(reverse("vulnerability_scanning:vulnerability_scans", args=[component.team.key]))
    count = len(rows)
    noun = _plural(count, "new vulnerability", "new vulnerabilities")
    severities = [row["severity"] for row in rows]
    worst = severities[0] if severities else ""

    lines = [
        _vulnerability_line(row["advisory_id"], row["severity"], row.get("package", ""), row.get("version", ""))
        for row in rows[:MAX_LISTED]
    ]
    if count > MAX_LISTED:
        lines.append(f"_…and {count - MAX_LISTED} more on the component page_")

    blocks = [
        _header(f"{severity_emoji(worst)} {noun} in {component.name}"),
        _section(f"A scan of *{_link(component_url, component.name)}* found {noun}.\n{_severity_counts(severities)}"),
        _divider(),
        _section("\n".join(lines)),
        _context(component.team),
        _buttons(("View component", component_url, "primary"), ("All vulnerabilities", vulnerabilities_url, "")),
    ]
    plain_counts = ", ".join(
        f"{severities.count(label)} {label}" for label in _SEVERITY_LABELS if severities.count(label)
    )
    text = f"{noun} in {component.name}" + (f": {plain_counts}." if plain_counts else ".")
    return Message(text=text, blocks=blocks)


def sort_worst_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unranked = len(SEVERITY_RANK)
    return sorted(
        rows,
        key=lambda row: (
            SEVERITY_RANK.get(row["severity"], unranked),
            -(row.get("cvss_score") or 0),
            row["advisory_id"],
        ),
    )


def digest_message(team: Workspace) -> Message:
    """The day's picture: what is open, what changed, what is waiting.

    The totals are the Vulnerabilities page's own, read through the same
    service, so the digest and the page never disagree about a number.
    """
    from sbomify.apps.plugins.models import VulnerabilityLifecycle
    from sbomify.apps.vulnerability_scanning.services.vex_submissions import pending_count
    from sbomify.apps.vulnerability_scanning.services.workspace_vulnerabilities import (
        VulnerabilityQuery,
        build_workspace_vulnerabilities,
    )

    page_url = _absolute(reverse("vulnerability_scanning:vulnerability_scans", args=[team.key]))
    listed = build_workspace_vulnerabilities(team, VulnerabilityQuery(per_page="5"))
    value = listed.value if listed.ok and listed.value is not None else {"summary": {}, "rows": []}
    summary = value["summary"]
    open_count = summary.get("vulnerabilities", 0)

    since = timezone.now() - timedelta(days=1)
    lifecycles = VulnerabilityLifecycle.objects.filter(component__team=team)
    opened = lifecycles.filter(first_seen_at__gte=since).count()
    fixed = lifecycles.filter(resolved_at__gte=since).count()
    waiting = pending_count(team.id)

    open_noun = _plural(open_count, "open vulnerability", "open vulnerabilities")
    blocks: list[dict[str, Any]] = [
        _header(f":bar_chart: Daily vulnerability digest for {team.name}"),
        _section(f"*{open_noun}* across *{_escape(team.name)}*."),
        _fields(
            [
                (f"{SEVERITY_EMOJI['critical']} Critical", str(summary.get("critical", 0))),
                (f"{SEVERITY_EMOJI['high']} High", str(summary.get("high", 0))),
                (f"{SEVERITY_EMOJI['medium']} Medium", str(summary.get("medium", 0))),
                (f"{SEVERITY_EMOJI['low']} Low", str(summary.get("low", 0))),
                (":rotating_light: Known exploited", str(summary.get("exploited", 0))),
                (":alarm_clock: Past fix-by date", str(summary.get("overdue", 0))),
            ]
        ),
        _divider(),
        _fields(
            [
                (":new: New in the last 24 hours", str(opened)),
                (":white_check_mark: Fixed in the last 24 hours", str(fixed)),
                (":inbox_tray: VEX rulings waiting", str(waiting)),
            ]
        ),
    ]
    rows = value["rows"]
    if rows:
        blocks += [
            _divider(),
            _section(
                "*Top priorities*\n"
                + "\n".join(
                    _vulnerability_line(
                        row.get("id", ""),
                        row.get("severity", ""),
                        row.get("package", ""),
                        row.get("version", ""),
                        row.get("component_name", ""),
                    )
                    for row in rows
                )
            ),
        ]
    buttons: list[tuple[str, str, str]] = [("Open vulnerabilities", page_url, "primary")]
    if waiting:
        buttons.append(("Review VEX queue", f"{page_url}?view=review", ""))
    blocks += [_context(team), _buttons(*buttons)]
    return Message(text=f"Vulnerability digest for {team.name}: {open_noun}.", blocks=blocks)
