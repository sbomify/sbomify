"""
Centralized access control service for components.

This module provides a single source of truth for component access control logic,
eliminating duplication across views and APIs.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.http import HttpRequest

from sbomify.apps.core.authz import READ_INTERNAL, ROLE_GUEST
from sbomify.apps.core.models import User
from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.sboms.models import Component
from sbomify.apps.teams.models import Team


@dataclass
class ComponentAccessResult:
    """Result of component access check."""

    has_access: bool
    reason: str
    requires_authentication: bool = False
    requires_access_request: bool = False
    access_request_status: str | None = None


def _user_has_signed_current_nda(user: User, team: Team) -> bool:
    """Check if user has signed the current company-wide NDA version.

    Optimized to use a single query with exists() to avoid fetching unnecessary data.

    Args:
        user: User instance to check
        team: Team instance to check NDA for

    Returns:
        True if user has signed the current NDA version, False otherwise.
        Returns True if no NDA is required.
    """
    company_nda = team.get_company_nda_document()
    if not company_nda:
        return True  # No NDA requirement

    from sbomify.apps.documents.access_models import NDASignature

    # Optimize: Single query to check if signature exists for current NDA
    # This avoids fetching the AccessRequest separately
    return (
        NDASignature.objects.live()
        .filter(
            access_request__team=team,
            access_request__user=user,
            nda_document=company_nda,
        )
        .exists()
    )


def _check_gated_access(user: User, team: Team) -> tuple[bool, bool]:
    """Check if user has gated access to components in a team.

    This is the core logic for gated access checking, used by both
    check_component_access and the Component model methods.

    Optimized to minimize database queries by checking member and access request
    in a single pass where possible.

    Args:
        user: User instance to check (must be authenticated)
        team: Team instance to check access for

    Returns:
        tuple: (has_access: bool, requires_nda_re_sign: bool)
    """
    if not user or not user.is_authenticated:
        return False, False

    from sbomify.apps.documents.access_models import AccessRequest
    from sbomify.apps.teams.models import Member

    # Membership is resolved BEFORE the revocation check. Revocation is an
    # *external* access control — it withdraws a trust-center grant — so it must
    # not out-rank an internal role. Checking it first meant a stale REVOKED row
    # permanently locked an internal member out of their own workspace's gated
    # content: revoke an external user, then later hire them and invite them as
    # an admin, and because their guest Member row was deleted a *new* row is
    # created, so neither the guest-upgrade cleanup (which returns early when the
    # row is `created`) nor the invitation-accept cleanup (which only fires when
    # an existing membership changes role) removes the REVOKED request. With no
    # UI to clear it, every gated check denied them, telling them to request
    # access from themselves.
    member = Member.objects.filter(team=team, user=user).select_related("team", "user").first()
    if member and member.role in READ_INTERNAL:
        # Internal members have full access without signing an NDA — the NDA
        # gates *external* access, and they can already read the workspace.
        return True, False

    # Revoked access request — deny regardless of any *guest* membership, so a
    # revoked user loses access even if member deletion hasn't completed yet.
    revoked_request = (
        AccessRequest.objects.filter(team=team, user=user, status=AccessRequest.Status.REVOKED)
        .select_related("team", "user")
        .first()
    )
    if revoked_request:
        # Ensure the guest membership is gone (in case revocation's own deletion
        # failed). ``member`` was already fetched above, so only issue the write
        # when there is actually a guest row to remove — this is a read path, and
        # an unconditional DELETE took row locks on every check for a revoked
        # user, almost always deleting nothing.
        if member is not None and member.role == ROLE_GUEST:
            Member.objects.filter(team=team, user=user, role=ROLE_GUEST).delete()
        return False, False

    if member:
        if member.role == ROLE_GUEST:
            # Guest members must have signed the current NDA
            if not _user_has_signed_current_nda(user, team):
                return False, True  # Access denied, needs to re-sign NDA
            return True, False

    # Check for approved access request (for non-members who were granted access)
    # Note: We already checked for revoked requests above, so this will only find approved ones
    approved_request = (
        AccessRequest.objects.filter(team=team, user=user, status=AccessRequest.Status.APPROVED)
        .select_related("team", "user")
        .first()
    )
    if approved_request:
        # Even with approved request, check if NDA is required and signed
        if not _user_has_signed_current_nda(user, team):
            return False, True  # Access denied, needs to re-sign NDA
        return True, False

    return False, False


def check_component_access(
    request: HttpRequest, component: Component, team: Team | None = None
) -> ComponentAccessResult:
    """Check if user has access to a component.

    This is the single source of truth for component access control logic.
    All views and APIs should use this function instead of duplicating logic.

    Args:
        request: HTTP request object
        component: Component instance to check access for
        team: Optional team instance (uses component.team if not provided)

    Returns:
        ComponentAccessResult with access status and reason
    """
    if not team:
        team = component.team

    # Public components are accessible to everyone
    if component.visibility == Component.Visibility.PUBLIC:
        return ComponentAccessResult(
            has_access=True,
            reason="public",
            requires_authentication=False,
            requires_access_request=False,
        )

    # Gated components require authentication and access approval
    if component.visibility == Component.Visibility.GATED:
        if not request.user.is_authenticated:
            return ComponentAccessResult(
                has_access=False,
                reason="gated_requires_authentication",
                requires_authentication=True,
                requires_access_request=True,
            )

        # A workspace-scoped token must not reach a component outside its workspace, even when
        # the user's own membership/NDA would otherwise grant gated access (mirror the scope
        # gate in verify_item_access that the PRIVATE branch below relies on).
        token_team = getattr(request, "token_team", None)
        if token_team is not None and team is not None and team.id != token_team.id:
            return ComponentAccessResult(
                has_access=False,
                reason="token_workspace_scope",
                requires_authentication=True,
                requires_access_request=False,
            )

        # Check if user has gated access
        has_access, needs_nda_re_sign = _check_gated_access(request.user, team)
        if has_access:
            return ComponentAccessResult(
                has_access=True,
                reason="gated_access_granted",
                requires_authentication=True,
                requires_access_request=False,
            )

        if needs_nda_re_sign:
            return ComponentAccessResult(
                has_access=False,
                reason="gated_nda_re_sign_required",
                requires_authentication=True,
                requires_access_request=True,
            )

        # User doesn't have access - check if they have a pending/rejected/revoked request
        from sbomify.apps.documents.access_models import AccessRequest

        access_request = (
            AccessRequest.objects.filter(
                team=team,
                user=request.user,
                status__in=(AccessRequest.Status.PENDING, AccessRequest.Status.REJECTED, AccessRequest.Status.REVOKED),
            )
            .order_by("-requested_at")
            .first()
        )

        if access_request:
            return ComponentAccessResult(
                has_access=False,
                reason=f"gated_access_request_{access_request.status}",
                requires_authentication=True,
                requires_access_request=True,
                access_request_status=access_request.status,
            )

        return ComponentAccessResult(
            has_access=False,
            reason="gated_access_required",
            requires_authentication=True,
            requires_access_request=True,
        )

    # Private components require owner/admin access
    if component.visibility == Component.Visibility.PRIVATE:
        if not request.user.is_authenticated:
            return ComponentAccessResult(
                has_access=False,
                reason="private_requires_authentication",
                requires_authentication=True,
                requires_access_request=False,
            )

        if verify_item_access(request, component, list(READ_INTERNAL)):
            return ComponentAccessResult(
                has_access=True,
                reason="private_access_granted",
                requires_authentication=True,
                requires_access_request=False,
            )

        return ComponentAccessResult(
            has_access=False,
            reason="private_access_denied",
            requires_authentication=True,
            requires_access_request=False,
        )

    # Unknown visibility - deny access for safety
    return ComponentAccessResult(
        has_access=False,
        reason="unknown_visibility",
        requires_authentication=False,
        requires_access_request=False,
    )


def check_component_access_for_user(
    user: User, component: Component, team: Team | None = None
) -> ComponentAccessResult:
    """Access check for a user with no HTTP-request context.

    Use this for delegated checks (e.g. re-validating a signed-download
    token's user) where there is no authenticated session to trust. It
    evaluates LIVE database state only: it builds a stub request carrying
    just the user and an EMPTY session, so the PRIVATE-component path in
    ``verify_item_access`` never short-circuits on a (possibly stale)
    ``session["user_teams"]`` role cache. Routes through
    ``check_component_access`` so the rules stay in one place.
    """
    stub = HttpRequest()
    stub.user = user
    # Empty session -> verify_item_access skips its session role-cache and
    # falls through to the authoritative DB membership lookup.
    stub.session = {}  # type: ignore[assignment]
    return check_component_access(stub, component, team)
