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
        if component.user_has_gated_access(request.user, team):
            return ComponentAccessResult(
                has_access=True,
                reason="gated_access_granted",
                requires_authentication=True,
                requires_access_request=False,
            )

        # User doesn't have access - check if they have a pending/rejected request
        from sbomify.apps.documents.access_models import AccessRequest

        access_request = (
            AccessRequest.objects.filter(
                team=team,
                user=request.user,
                status__in=(AccessRequest.Status.PENDING, AccessRequest.Status.REJECTED),
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
