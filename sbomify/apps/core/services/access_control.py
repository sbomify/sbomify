"""
Centralized access control service for components.

This module provides a single source of truth for component access control logic,
eliminating duplication across views and APIs.
"""

from dataclasses import dataclass

from django.http import HttpRequest

from sbomify.apps.core.utils import verify_item_access
from sbomify.apps.sboms.models import Component


@dataclass
class ComponentAccessResult:
    """Result of component access check."""

    has_access: bool
    reason: str
    requires_authentication: bool = False
    requires_access_request: bool = False
    access_request_status: str | None = None


def _user_has_signed_current_nda(user, team):
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
    return NDASignature.objects.filter(
        access_request__team=team,
        access_request__user=user,
        nda_document=company_nda,
    ).exists()


def _check_gated_access(user, team):
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

    # First check if user has a revoked access request - if so, deny access regardless of membership
    # This ensures revoked users lose access even if member deletion hasn't completed yet
    revoked_request = (
        AccessRequest.objects.filter(team=team, user=user, status=AccessRequest.Status.REVOKED)
        .select_related("team", "user")
        .first()
    )
    if revoked_request:
        # User's access has been revoked, deny access
        # Also ensure guest membership is removed (in case deletion failed)
        Member.objects.filter(team=team, user=user, role="guest").delete()
        return False, False

    # Optimize: Check member first (most common case for owners/admins)
    # This avoids querying AccessRequest if user is already a member
    member = Member.objects.filter(team=team, user=user).select_related("team", "user").first()
    if member:
        if member.role in ("owner", "admin"):
            # Owners/admins have full access without signing NDA
            # (revoked requests don't apply to owners/admins as they're not guest access)
            return True, False
        if member.role == "guest":
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


def check_component_access(request: HttpRequest, component: Component, team=None) -> ComponentAccessResult:
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

        if verify_item_access(request, component, ["owner", "admin"]):
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
