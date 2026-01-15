from __future__ import annotations

from django.utils import timezone

from sbomify.apps.core.domain.exceptions import PermissionDeniedError

from .models import Invitation, Member, Team


def count_team_members(team_id: str) -> int:
    return Member.objects.filter(team_id=team_id).count()


def count_team_owners(team_id: str) -> int:
    return Member.objects.filter(team_id=team_id, role="owner").count()


def count_team_pending_invites(team_id: str) -> int:
    return Invitation.objects.filter(team_id=team_id, expires_at__gt=timezone.now()).count()


def get_team_user_counts(team_id: str) -> tuple[int, int, int]:
    members = count_team_members(team_id)
    pending = count_team_pending_invites(team_id)
    return members, pending, members + pending


def get_member_role(user_id: int, team_id: str) -> str | None:
    return Member.objects.filter(user_id=user_id, team_id=team_id).values_list("role", flat=True).first()


def require_team_member(user, team: Team, allowed_roles: list[str] | None = None) -> Member:
    member = Member.objects.filter(user=user, team=team).first()
    if not member:
        raise PermissionDeniedError("Access denied")
    if allowed_roles and member.role not in allowed_roles:
        raise PermissionDeniedError("You don't have sufficient permissions to access this page")
    return member
