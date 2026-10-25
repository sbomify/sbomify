"""Workspace websocket messages for membership, invitations and custom domains.

Every member who may read the workspace receives these, so a payload carries
ids, an action and a status, never an email address or a domain name. They are
refresh triggers: the page that hears one re-fetches what it shows.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from sbomify.apps.core.utils import broadcast_to_workspace


def broadcast_on_commit(workspace_key: str | None, message_type: str, data: dict[str, Any]) -> None:
    """Send ``message_type`` to the workspace once the current transaction commits.

    A rollback sends nothing, so no page refreshes for a change that never
    happened. Outside a transaction it is sent straight away.
    """
    if not workspace_key:
        return
    payload = dict(data)
    transaction.on_commit(
        lambda: broadcast_to_workspace(workspace_key=workspace_key, message_type=message_type, data=payload)
    )


def broadcast_member_updated(workspace_key: str | None, user_id: Any, action: str) -> None:
    """A member was ``added``, ``removed`` or had their role changed (``role_changed``)."""
    broadcast_on_commit(workspace_key, "member_updated", {"user_id": str(user_id), "action": action})


def broadcast_invitation_updated(workspace_key: str | None, invitation_id: Any, action: str) -> None:
    """An invitation was ``created``, ``accepted`` or ``revoked``."""
    broadcast_on_commit(workspace_key, "invitation_updated", {"invitation_id": str(invitation_id), "action": action})


def broadcast_custom_domain_updated(workspace_key: str | None, status: str) -> None:
    """A custom domain verification finished as ``verified`` or ``failed``."""
    broadcast_on_commit(workspace_key, "custom_domain_updated", {"status": status})
