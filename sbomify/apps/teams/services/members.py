"""Changing the role of someone already in a workspace.

The members page and the API both come through here, so the owner/admin rules
and the last-owner guard cannot drift between them. The rules themselves live in
``teams.permissions.check_role_change``.
"""

from __future__ import annotations

from typing import Any

from django.core.cache import cache
from django.db import transaction

from sbomify.apps.core.authz import ROLE_BOT, ROLE_GUEST
from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.teams.models import Member, Workspace
from sbomify.apps.teams.permissions import check_role_change


def change_member_role(actor: Any, team: Workspace, member_id: int, role: str) -> ServiceResult[Member]:
    """Move membership ``member_id`` of ``team`` to ``role`` on behalf of ``actor``.

    Fails with 404 for a membership that is not in this workspace (or is a guest
    or bot, which are not changed here), 403 when the actor may not make the
    change, and 400 for a refusal the actor can act on, such as demoting the
    only owner. Setting the role a member already holds succeeds and writes
    nothing.
    """
    with transaction.atomic():
        # Removals take this same lock before checking permissions and deleting.
        # Lock the workspace first so every path uses the same lock order.
        team = Workspace.objects.select_for_update().get(pk=team.pk)
        target = (
            Member.objects.select_for_update()
            .select_related("team")
            .filter(team=team, pk=member_id)
            .exclude(role__in=(ROLE_GUEST, ROLE_BOT))
            .first()
        )
        if target is None:
            return ServiceResult.failure("Member not found", status_code=404)

        if target.role == role:
            return ServiceResult.success(target)

        denial = check_role_change(actor, target, role)
        if denial:
            return ServiceResult.failure(denial.message, status_code=403 if denial.forbidden else 400)

        target.role = role
        target.save(update_fields=["role"])

    # The member's cached workspace list carries their role; drop it so the
    # change takes effect on their next request rather than when the cache ages
    # out.
    cache.set(f"user_teams_invalidate:{target.user_id}", True, timeout=600)
    return ServiceResult.success(target)
