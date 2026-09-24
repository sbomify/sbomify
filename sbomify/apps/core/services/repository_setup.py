"""Repository setup credentials, separate from the publish-only CI token."""

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core.authz import ADMINISTER
from sbomify.apps.core.models import User
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.teams.models import Member

SETUP_DESCRIPTION = "Repository setup"
SETUP_SCOPES = [
    "workspace:read",
    "workspace:manage",
    "product:read",
    "product:create",
    "product:manage",
    "product:set_visibility",
    "component:read_internal",
    "component:access",
    "component:create",
    "component:manage",
    "component:set_visibility",
    "component:manage_publishers",
]


@transaction.atomic
def create_setup_credential(user: User, workspace_key: str, previous_id: int | None) -> ServiceResult[dict[str, Any]]:
    membership = (
        Member.objects.select_for_update().filter(user=user, team__key=workspace_key, role__in=ADMINISTER).first()
    )
    if membership is None:
        return ServiceResult.failure("A workspace owner or admin must create the setup token.", status_code=403)

    if previous_id is not None:
        previous = AccessToken.objects.filter(
            pk=previous_id, user=user, team_id=membership.team_id, description=SETUP_DESCRIPTION, scopes=SETUP_SCOPES
        ).first()
        if previous is None:
            return ServiceResult.failure("This setup token is no longer available. Reload the page.", status_code=404)
        previous.delete()

    raw_value = create_personal_access_token(user)
    expires_at = timezone.now() + timedelta(days=7)
    credential = AccessToken.objects.create(
        encoded_token=raw_value,
        user=user,
        team_id=membership.team_id,
        description=SETUP_DESCRIPTION,
        scopes=SETUP_SCOPES,
        expires_at=expires_at,
    )
    return ServiceResult.success({"id": credential.pk, "token": raw_value, "expires_at": expires_at.isoformat()})
