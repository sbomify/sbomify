"""How an audit event reads on screen."""

from __future__ import annotations

from typing import Any

from .models import ActorType, AuditEvent, Channel, Outcome
from .signals import TRACKED

# Labels for the action filter. Targets come from the tracked models, so a
# model added there shows up here without a second edit.
_EXTRA_FILTERS: tuple[tuple[str, str], ...] = (
    ("auth", "Sign-ins"),
    ("agent", "Agent tool calls"),
    ("audit_log", "Audit log"),
    ("request", "Other requests"),
)

ACTION_FILTERS: tuple[tuple[str, str], ...] = tuple(
    sorted(
        [(t.name, t.name.replace("_", " ").capitalize()) for t in TRACKED] + list(_EXTRA_FILTERS),
        key=lambda item: item[1],
    )
)

_VERBS = {
    "created": "created",
    "updated": "updated",
    "deleted": "deleted",
    "signed_in": "signed in",
    "signed_out": "signed out",
    "tool_call": "tool call",
    "exported": "exported",
}

_OUTCOME_VARIANTS: dict[str, str] = {Outcome.SUCCESS: "success", Outcome.FAILURE: "warning", Outcome.DENIED: "danger"}
_CHANNEL_LABELS = dict(Channel.choices)


_LABELS = {
    "member.created": "Member added",
    "member.updated": "Member role changed",
    "member.deleted": "Member removed",
    "invitation.created": "Invitation sent",
    "invitation.deleted": "Invitation closed",
    "access_token.created": "API token created",
    "access_token.updated": "API token updated",
    "access_token.deleted": "API token revoked",
    "product_component.created": "Component added to product",
    "product_component.deleted": "Component removed from product",
    "trusted_publisher.created": "Trusted publisher added",
    "trusted_publisher.deleted": "Trusted publisher removed",
    "workspace.updated": "Workspace settings changed",
    "audit_log.exported": "Audit log exported",
    "agent.tool_call": "Agent tool call",
}


def action_label(action: str) -> str:
    if action in _LABELS:
        return _LABELS[action]
    subject, _, verb = action.partition(".")
    if subject == "request":
        return f"{verb.upper()} request"
    if subject == "auth":
        return _VERBS.get(verb, verb).capitalize()
    words = subject.replace("_", " ")
    return f"{words.capitalize()} {_VERBS.get(verb, verb.replace('_', ' '))}".strip()


def _change_summary(metadata: dict[str, Any]) -> str:
    parts = []
    for name, change in (metadata.get("changes") or {}).items():
        if isinstance(change, dict):
            parts.append(f"{name.replace('_', ' ')}: {change.get('from')!s} → {change.get('to')!s}")
    for name in metadata.get("changed") or []:
        parts.append(f"{str(name).replace('_', ' ')} changed")
    return "; ".join(parts)


def describe(event: AuditEvent) -> dict[str, Any]:
    metadata = event.metadata or {}
    summary = _change_summary(metadata)
    if not summary and event.action.startswith("request.") and metadata.get("route"):
        summary = f"{event.path} ({event.status_code})" if event.status_code else event.path
    if not summary and event.action == "agent.tool_call":
        summary = "Write" if metadata.get("writes") else "Read"
    return {
        "event": event,
        "action_label": action_label(event.action),
        "target_type_label": event.target_type.replace("_", " ").capitalize(),
        "summary": summary[:300],
        "outcome_variant": _OUTCOME_VARIANTS.get(event.outcome, "secondary"),
        "channel_label": _CHANNEL_LABELS.get(event.channel, event.channel),
        "actor_detail": " · ".join(
            part
            for part in (
                event.get_actor_type_display() if event.actor_type != ActorType.USER else "",
                event.actor_role.capitalize(),
            )
            if part
        ),
        "actor_label": event.actor_label or (f"User {event.actor_user_id}" if event.actor_user_id else "Unknown"),
    }
