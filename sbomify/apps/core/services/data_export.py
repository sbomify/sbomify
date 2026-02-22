"""GDPR data export service."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sbomify.apps.core.models import User

logger = logging.getLogger(__name__)


def export_user_data(user: User) -> dict:
    """Export all user data for GDPR data portability.

    Returns a dict containing user profile, workspace memberships,
    API token metadata, SBOMs, and documents from user's workspaces.
    """
    from sbomify.apps.access_tokens.models import AccessToken
    from sbomify.apps.documents.models import Document
    from sbomify.apps.sboms.models import SBOM, Component
    from sbomify.apps.teams.models import Member

    profile = {
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "date_joined": user.date_joined.isoformat(),
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }

    memberships = Member.objects.filter(user=user).select_related("team")
    workspaces = [
        {
            "name": m.team.name,
            "key": m.team.key,
            "role": m.role,
            "is_default_team": m.is_default_team,
        }
        for m in memberships
    ]

    tokens = AccessToken.objects.filter(user=user)
    token_data = [{"description": t.description, "created_at": t.created_at.isoformat()} for t in tokens]

    team_ids = [m.team_id for m in memberships]

    component_ids = Component.objects.filter(team_id__in=team_ids).values_list("id", flat=True)

    sboms = SBOM.objects.filter(component_id__in=component_ids)
    sbom_data = [
        {
            "id": s.id,
            "name": s.name,
            "version": s.version,
            "format": s.format,
            "format_version": s.format_version,
            "filename": s.sbom_filename,
            "created_at": s.created_at.isoformat(),
            "source": s.source,
        }
        for s in sboms
    ]

    documents = Document.objects.filter(component_id__in=component_ids)
    document_data = [
        {
            "id": d.id,
            "name": d.name,
            "version": d.version,
            "document_type": d.document_type,
            "filename": d.document_filename,
            "created_at": d.created_at.isoformat(),
            "source": d.source,
            "file_size": d.file_size,
        }
        for d in documents
    ]

    return {
        "export_version": "1.0",
        "user": profile,
        "workspaces": workspaces,
        "api_tokens": token_data,
        "sboms": sbom_data,
        "documents": document_data,
    }
