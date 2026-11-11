"""The Trust Centers a reader has asked for access to, from the reader's side."""

from __future__ import annotations

from typing import Any

from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.core.url_utils import build_custom_domain_url
from sbomify.apps.documents.access_models import AccessRequest

#: How each status reads to the person who asked, and the badge it wears.
STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    AccessRequest.Status.PENDING: ("Waiting for review", "warning"),
    AccessRequest.Status.APPROVED: ("Access granted", "success"),
    AccessRequest.Status.REJECTED: ("Not approved", "danger"),
    AccessRequest.Status.REVOKED: ("Access withdrawn", "secondary"),
}


def list_reader_access_requests(user: Any, secure: bool = True) -> ServiceResult[list[dict[str, Any]]]:
    """Every Trust Center ``user`` has requested access to, newest first."""
    from django.urls import reverse

    rows = []
    for access_request in AccessRequest.objects.filter(user=user).select_related("team").order_by("-requested_at"):
        team = access_request.team
        label, variant = STATUS_DISPLAY.get(access_request.status, (access_request.get_status_display(), "secondary"))
        rows.append(
            {
                "id": access_request.id,
                "workspace_name": team.display_name,
                # A Trust Center on its own host is reached signed in, through the
                # handoff; one served from the app domain already shares the session.
                "trust_center_url": reverse(
                    "core:trust_center_sign_in"
                    if build_custom_domain_url(team, "/", secure)
                    else "core:workspace_public",
                    kwargs={"workspace_key": team.key},
                ),
                "status": access_request.status,
                "status_label": label,
                "status_variant": variant,
                "requested_at": access_request.requested_at,
                "decided_at": access_request.revoked_at or access_request.decided_at,
            }
        )
    return ServiceResult.success(rows)
