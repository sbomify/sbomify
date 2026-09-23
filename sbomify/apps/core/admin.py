from __future__ import annotations

import logging
from typing import Any

from allauth.socialaccount.models import SocialAccount
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from sbomify.apps.billing.admin import BillingPlanAdmin
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.documents.admin import DocumentAdmin
from sbomify.apps.documents.models import Document
from sbomify.apps.sboms.admin import SBOMAdmin
from sbomify.apps.sboms.models import SBOM  # SBOM still lives in sboms app
from sbomify.apps.teams.admin import InvitationAdmin, MemberAdmin, TeamAdmin
from sbomify.apps.teams.models import Invitation, Member, Team
from sbomify.apps.vulnerability_scanning.admin import (
    ComponentDependencyTrackMappingAdmin,
    DependencyTrackServerAdmin,
    TeamVulnerabilitySettingsAdmin,
)
from sbomify.apps.vulnerability_scanning.models import (
    ComponentDependencyTrackMapping,
    DependencyTrackServer,
    TeamVulnerabilitySettings,
)

from .models import Component, Product, User

logger = logging.getLogger(__name__)


class SbomifyAdminSite(admin.AdminSite):
    """The Django admin site.

    Stock, deliberately. The metrics dashboard that used to hang off this
    class now lives at /ops/ as a page of its own, so the admin is back to
    being the model admin and nothing else.
    """

    site_header = "sbomify administration"
    site_title = "sbomify admin"
    index_title = "sbomify administration"


class CustomUserAdmin(UserAdmin):  # type: ignore[type-arg]
    """Custom admin for User model with Keycloak integration."""

    list_display = list(UserAdmin.list_display) + [  # type: ignore[misc]
        "email_verified",
        "email_verified_status",
        "newsletter_opt_in",
        "last_login_display",
        "social_accounts",
    ]
    readonly_fields = list(UserAdmin.readonly_fields) + [
        "email_verified",
        "email_verified_status",
        "last_login_display",
        "social_accounts",
    ]
    list_filter = list(UserAdmin.list_filter) + ["last_login", "email_verified", "newsletter_opt_in", "is_active"]
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email", "email_verified", "newsletter_opt_in")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
        ("Social Accounts", {"fields": ("social_accounts",)}),
    )

    @admin.display(
        description="Last Login",
        ordering="last_login",
    )
    def last_login_display(self, obj: Any) -> str:
        """Display last login time in a user-friendly format."""
        if not obj.last_login:
            return format_html('<span style="color: #666;">Never</span>')

        now = timezone.now()
        diff = now - obj.last_login

        if diff.days == 0:
            if diff.seconds < 60:
                return format_html('<span style="color: #417690;">Just now</span>')
            elif diff.seconds < 3600:
                minutes = diff.seconds // 60
                return format_html('<span style="color: #417690;">{} minutes ago</span>', minutes)
            else:
                hours = diff.seconds // 3600
                return format_html('<span style="color: #417690;">{} hours ago</span>', hours)
        elif diff.days == 1:
            return format_html('<span style="color: #417690;">Yesterday</span>')
        elif diff.days < 7:
            return format_html('<span style="color: #417690;">{} days ago</span>', diff.days)
        else:
            return format_html('<span style="color: #666;">{}</span>', obj.last_login.strftime("%Y-%m-%d %H:%M"))

    @admin.display(
        description="Email Verified Status",
        boolean=False,  # We're using custom HTML output
    )
    def email_verified_status(self, obj: Any) -> str:
        """Get email verification status.

        Uses Django User.email_verified as the primary source of truth,
        with fallback to social account extra_data for legacy accounts.
        """
        # Primary: Use Django User model field. If this is True we intentionally
        # skip the legacy social-account-based fallback below, because
        # email_verified is the authoritative source for current users.
        if obj.email_verified:
            return format_html('<span style="color: #28a745;">Verified</span>')

        # Fallback: Check social account extra_data
        # (for accounts created before email_verified sync was implemented)
        auth = obj.socialaccount_set.first()
        if not auth:
            return format_html('<span style="color: #666;">No social account</span>')

        # Check provider-specific verification field in extra_data
        if auth.extra_data:
            if auth.provider == "keycloak":
                verified = auth.extra_data.get("email_verified", False)
            elif auth.provider == "github":
                verified = auth.extra_data.get("email_verified", False)
            elif auth.provider == "google":
                verified = auth.extra_data.get("verified_email", False)
            else:
                verified = False

            if verified:
                return format_html('<span style="color: #28a745;">Verified</span>')

        return format_html('<span style="color: #dc3545;">Not Verified</span>')

    def social_accounts(self, obj: Any) -> str:
        """Display social accounts for the user."""
        social_auths = SocialAccount.objects.filter(user=obj)
        if not social_auths:
            return format_html('<span style="color: #666;">None</span>')

        return format_html_join(
            format_html("<br>"),
            "{}: {} {}",
            (
                (
                    auth.provider.capitalize(),
                    auth.uid,
                    "✓" if auth.extra_data.get("email_verified", False) else "✗",
                )
                for auth in social_auths
            ),
        )


class ProductAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Admin configuration for Product model."""

    list_display = (
        "id",
        "name",
        "workspace",
        "is_public",
        "created_at",
    )

    list_filter = (
        "is_public",
        "team",
        "created_at",
    )

    search_fields = (
        "id",
        "name",
        "description",
        "team__name",
    )

    readonly_fields = (
        "id",
        "created_at",
    )

    @admin.display(description="Workspace", ordering="team__name")
    def workspace(self, obj: Any) -> str:
        """Display the workspace (team) name for the Product."""
        return obj.team.name if obj.team else "No Team"


class ComponentAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Admin configuration for Component model."""

    list_display = (
        "id",
        "name",
        "component_type",
        "workspace",
        "visibility",
        "created_at",
    )

    list_filter = (
        "component_type",
        "visibility",
        "team",
        "created_at",
    )

    search_fields = (
        "id",
        "name",
        "team__name",
    )

    readonly_fields = (
        "id",
        "created_at",
    )

    @admin.display(description="Workspace", ordering="team__name")
    def workspace(self, obj: Any) -> str:
        """Display the workspace (team) name for the Component."""
        return obj.team.name if obj.team else "No Team"


# Create custom admin site
admin_site = SbomifyAdminSite(name="admin")

# Register all models with our custom admin site
admin_site.register(User, CustomUserAdmin)
admin_site.register(Team, TeamAdmin)
admin_site.register(Member, MemberAdmin)
admin_site.register(Invitation, InvitationAdmin)
admin_site.register(Product, ProductAdmin)
admin_site.register(Component, ComponentAdmin)
admin_site.register(SBOM, SBOMAdmin)
admin_site.register(Document, DocumentAdmin)

# Register billing models
admin_site.register(BillingPlan, BillingPlanAdmin)

# Register vulnerability scanning models
admin_site.register(DependencyTrackServer, DependencyTrackServerAdmin)
admin_site.register(TeamVulnerabilitySettings, TeamVulnerabilitySettingsAdmin)
admin_site.register(ComponentDependencyTrackMapping, ComponentDependencyTrackMappingAdmin)
