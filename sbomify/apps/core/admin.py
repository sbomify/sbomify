import logging
from datetime import timedelta
from functools import wraps

from allauth.socialaccount.models import SocialAccount
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from sbomify.apps.billing.admin import BillingPlanAdmin
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.documents.admin import DocumentAdmin
from sbomify.apps.documents.models import Document
from sbomify.apps.onboarding.models import OnboardingStatus
from sbomify.apps.sboms.admin import SBOMAdmin
from sbomify.apps.sboms.models import SBOM  # SBOM still lives in sboms app
from sbomify.apps.teams.admin import InvitationAdmin, MemberAdmin, TeamAdmin
from sbomify.apps.teams.models import Invitation, Member, Team
from sbomify.apps.vulnerability_scanning.admin import (
    ComponentDependencyTrackMappingAdmin,
    DependencyTrackServerAdmin,
    TeamVulnerabilitySettingsAdmin,
    VulnerabilityScanResultAdmin,
)
from sbomify.apps.vulnerability_scanning.models import (
    ComponentDependencyTrackMapping,
    DependencyTrackServer,
    TeamVulnerabilitySettings,
    VulnerabilityScanResult,
)

from .models import Component, Product, Project, User

logger = logging.getLogger(__name__)


def admin_dashboard_required(view_func):
    """Decorator to check if user has permission to view dashboard."""

    @wraps(view_func)
    def wrapper(self, request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view_func(self, request, *args, **kwargs)

    return wrapper


class DashboardView(admin.AdminSite):
    site_header = "sbomify administration"
    site_title = "sbomify admin"
    index_title = "sbomify administration"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path("dashboard/", self.admin_view(self.dashboard_view), name="admin_dashboard"),
            path("dashboard/billing/", self.admin_view(self.dashboard_billing_view), name="admin_dashboard_billing"),
            path("dashboard/growth/", self.admin_view(self.dashboard_growth_view), name="admin_dashboard_growth"),
            path("dashboard/funnel/", self.admin_view(self.dashboard_funnel_view), name="admin_dashboard_funnel"),
            path("dashboard/health/", self.admin_view(self.dashboard_health_view), name="admin_dashboard_health"),
        ]
        return custom_urls + urls

    def index(self, request, extra_context=None):
        extra_context = extra_context or {}
        app_list = self.get_app_list(request)

        # Add dashboard link to the index
        dashboard_app = {
            "name": "Dashboard",
            "app_label": "core",
            "app_url": "/admin/dashboard/",
            "has_module_perms": True,
            "models": [
                {
                    "name": "System Dashboard",
                    "object_name": "Dashboard",
                    "admin_url": "/admin/dashboard/",
                    "view_only": True,
                }
            ],
        }
        app_list.insert(0, dashboard_app)
        extra_context["app_list"] = app_list
        return super().index(request, extra_context)

    def get_dashboard_stats(self):
        """Get dashboard statistics with caching."""
        cache_key = "admin_dashboard_stats"
        stats = cache.get(cache_key)

        if stats is None:
            try:
                now = timezone.now()
                seven_days_ago = now - timedelta(days=7)
                thirty_days_ago = now - timedelta(days=30)

                # Get signups by day for trend chart
                signups_by_day = list(
                    User.objects.filter(date_joined__gte=thirty_days_ago)
                    .annotate(day=TruncDate("date_joined"))
                    .values("day")
                    .annotate(count=Count("id"))
                    .order_by("day")
                )
                # Format dates for JavaScript
                for item in signups_by_day:
                    item["day"] = item["day"].strftime("%m/%d") if item["day"] else ""

                stats = {
                    # Basic counts (existing)
                    "users": User.objects.count(),
                    "teams": Team.objects.count(),
                    "products": Product.objects.count(),
                    "projects": Project.objects.count(),
                    "components": Component.objects.count(),
                    "sboms": SBOM.objects.count(),
                    "users_per_team": list(
                        Team.objects.annotate(user_count=Count("members")).values("name", "user_count")[:15]
                    ),
                    # Billing & Subscription metrics
                    "teams_by_plan": list(
                        Team.objects.values("billing_plan").annotate(count=Count("id")).order_by("-count")
                    ),
                    # Subscription status breakdown (replaces incorrect teams_with_stripe)
                    "teams_active": Team.objects.filter(billing_plan_limits__subscription_status="active").count(),
                    "teams_trialing": Team.objects.filter(billing_plan_limits__subscription_status="trialing").count(),
                    "teams_past_due": Team.objects.filter(billing_plan_limits__subscription_status="past_due").count(),
                    "teams_canceled": Team.objects.filter(billing_plan_limits__subscription_status="canceled").count(),
                    # User Growth metrics
                    "new_users_30d": User.objects.filter(date_joined__gte=thirty_days_ago).count(),
                    "new_teams_30d": Team.objects.filter(created_at__gte=thirty_days_ago).count(),
                    # 30-day metrics for content
                    "products_30d": Product.objects.filter(created_at__gte=thirty_days_ago).count(),
                    "projects_30d": Project.objects.filter(created_at__gte=thirty_days_ago).count(),
                    "components_30d": Component.objects.filter(created_at__gte=thirty_days_ago).count(),
                    "active_users_7d": User.objects.filter(last_login__gte=seven_days_ago).count(),
                    "active_users_30d": User.objects.filter(last_login__gte=thirty_days_ago).count(),
                    "users_never_logged_in": User.objects.filter(last_login__isnull=True).count(),
                    "signups_by_day": signups_by_day,
                    # Onboarding Funnel metrics
                    "onboarding_wizard_completed": OnboardingStatus.objects.filter(has_completed_wizard=True).count(),
                    "onboarding_component_created": OnboardingStatus.objects.filter(has_created_component=True).count(),
                    "onboarding_sbom_uploaded": OnboardingStatus.objects.filter(has_uploaded_sbom=True).count(),
                    "pending_invitations": Invitation.objects.filter(expires_at__gt=now).count(),
                    "expired_invitations": Invitation.objects.filter(expires_at__lte=now).count(),
                    # Product Health metrics
                    "public_workspaces": Team.objects.filter(is_public=True).count(),
                    "private_workspaces": Team.objects.filter(is_public=False).count(),
                    "custom_domains_configured": Team.objects.exclude(custom_domain__isnull=True)
                    .exclude(custom_domain="")
                    .count(),
                    "custom_domains_validated": Team.objects.filter(custom_domain_validated=True).count(),
                    "sboms_30d": SBOM.objects.filter(created_at__gte=thirty_days_ago).count(),
                    # Documents metrics
                    "documents": Document.objects.count(),
                    "documents_30d": Document.objects.filter(created_at__gte=thirty_days_ago).count(),
                    "documents_by_type": list(
                        Document.objects.values("document_type").annotate(count=Count("id")).order_by("-count")
                    ),
                    "compliance_documents": Document.objects.filter(
                        document_type__in=["compliance", "evidence", "license"]
                    ).count(),
                    # Email Verification
                    "email_verified_users": User.objects.filter(email_verified=True).count(),
                }
                # Cache for 5 minutes
                cache.set(cache_key, stats, 300)
            except Exception as e:
                logger.error(f"Error fetching dashboard stats: {str(e)}")
                stats = {
                    "error": "Unable to fetch statistics",
                    "users": 0,
                    "teams": 0,
                    "products": 0,
                    "projects": 0,
                    "components": 0,
                    "sboms": 0,
                    "users_per_team": [],
                    "teams_by_plan": [],
                    # Subscription status breakdown
                    "teams_active": 0,
                    "teams_trialing": 0,
                    "teams_past_due": 0,
                    "teams_canceled": 0,
                    "new_users_30d": 0,
                    "new_teams_30d": 0,
                    # 30-day content metrics
                    "products_30d": 0,
                    "projects_30d": 0,
                    "components_30d": 0,
                    "active_users_7d": 0,
                    "active_users_30d": 0,
                    "users_never_logged_in": 0,
                    "signups_by_day": [],
                    "onboarding_wizard_completed": 0,
                    "onboarding_component_created": 0,
                    "onboarding_sbom_uploaded": 0,
                    "pending_invitations": 0,
                    "expired_invitations": 0,
                    "public_workspaces": 0,
                    "private_workspaces": 0,
                    "custom_domains_configured": 0,
                    "custom_domains_validated": 0,
                    "sboms_30d": 0,
                    "documents": 0,
                    "documents_30d": 0,
                    "documents_by_type": [],
                    "compliance_documents": 0,
                    "email_verified_users": 0,
                }

        return stats

    @admin_dashboard_required
    def dashboard_view(self, request):
        """View for the admin dashboard overview."""
        context = {
            **self.each_context(request),
            "title": "System Dashboard",
            "stats": self.get_dashboard_stats(),
            "app_label": "core",
            "has_permission": True,
            "active_page": "overview",
        }
        return TemplateResponse(request, "admin/dashboard.html", context)

    @admin_dashboard_required
    def dashboard_billing_view(self, request):
        """View for the billing dashboard page."""
        context = {
            **self.each_context(request),
            "title": "Billing Dashboard",
            "stats": self.get_dashboard_stats(),
            "app_label": "core",
            "has_permission": True,
            "active_page": "billing",
        }
        return TemplateResponse(request, "admin/dashboard_billing.html", context)

    @admin_dashboard_required
    def dashboard_growth_view(self, request):
        """View for the user growth dashboard page."""
        context = {
            **self.each_context(request),
            "title": "User Growth Dashboard",
            "stats": self.get_dashboard_stats(),
            "app_label": "core",
            "has_permission": True,
            "active_page": "growth",
        }
        return TemplateResponse(request, "admin/dashboard_growth.html", context)

    @admin_dashboard_required
    def dashboard_funnel_view(self, request):
        """View for the onboarding funnel dashboard page."""
        context = {
            **self.each_context(request),
            "title": "Onboarding Dashboard",
            "stats": self.get_dashboard_stats(),
            "app_label": "core",
            "has_permission": True,
            "active_page": "funnel",
        }
        return TemplateResponse(request, "admin/dashboard_funnel.html", context)

    @admin_dashboard_required
    def dashboard_health_view(self, request):
        """View for the product health dashboard page."""
        context = {
            **self.each_context(request),
            "title": "Product Health Dashboard",
            "stats": self.get_dashboard_stats(),
            "app_label": "core",
            "has_permission": True,
            "active_page": "health",
        }
        return TemplateResponse(request, "admin/dashboard_health.html", context)

    def get_social_accounts(self, obj):
        accounts = obj.socialaccount_set.all()
        if not accounts:
            return format_html('<span style="color: #666;">None</span>')
        return format_html_join(
            format_html("<br>"),
            "{}: {}",
            ((account.provider, account.uid) for account in accounts),
        )

    get_social_accounts.short_description = "Social Accounts"


class CustomUserAdmin(UserAdmin):
    """Custom admin for User model with Keycloak integration."""

    list_display = UserAdmin.list_display + (
        "email_verified",
        "email_verified_status",
        "last_login_display",
        "social_accounts",
    )
    readonly_fields = UserAdmin.readonly_fields + (
        "email_verified",
        "email_verified_status",
        "last_login_display",
        "social_accounts",
    )
    list_filter = UserAdmin.list_filter + ("last_login", "email_verified", "is_active")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email", "email_verified")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
        ("Social Accounts", {"fields": ("social_accounts",)}),
    )

    @admin.display(
        description="Last Login",
        ordering="last_login",
    )
    def last_login_display(self, obj):
        """Display last login time in a user-friendly format."""
        if not obj.last_login:
            return format_html('<span style="color: #666;">Never</span>')

        from django.utils import timezone

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
    def email_verified_status(self, obj):
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

    def social_accounts(self, obj):
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


class ProjectAdmin(admin.ModelAdmin):
    """Admin configuration for Project model."""

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
        "team__name",
    )

    readonly_fields = (
        "id",
        "created_at",
    )

    def workspace(self, obj):
        """Display the workspace (team) name for the Project."""
        return obj.team.name if obj.team else "No Team"

    workspace.short_description = "Workspace"
    workspace.admin_order_field = "team__name"


class ProductAdmin(admin.ModelAdmin):
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

    def workspace(self, obj):
        """Display the workspace (team) name for the Product."""
        return obj.team.name if obj.team else "No Team"

    workspace.short_description = "Workspace"
    workspace.admin_order_field = "team__name"


class ComponentAdmin(admin.ModelAdmin):
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

    def workspace(self, obj):
        """Display the workspace (team) name for the Component."""
        return obj.team.name if obj.team else "No Team"

    workspace.short_description = "Workspace"
    workspace.admin_order_field = "team__name"


# Create custom admin site
admin_site = DashboardView(name="admin")

# Register all models with our custom admin site
admin_site.register(User, CustomUserAdmin)
admin_site.register(Team, TeamAdmin)
admin_site.register(Member, MemberAdmin)
admin_site.register(Invitation, InvitationAdmin)
admin_site.register(Product, ProductAdmin)
admin_site.register(Project, ProjectAdmin)
admin_site.register(Component, ComponentAdmin)
admin_site.register(SBOM, SBOMAdmin)
admin_site.register(Document, DocumentAdmin)

# Register billing models
admin_site.register(BillingPlan, BillingPlanAdmin)

# Register vulnerability scanning models
admin_site.register(DependencyTrackServer, DependencyTrackServerAdmin)
admin_site.register(TeamVulnerabilitySettings, TeamVulnerabilitySettingsAdmin)
admin_site.register(ComponentDependencyTrackMapping, ComponentDependencyTrackMappingAdmin)
admin_site.register(VulnerabilityScanResult, VulnerabilityScanResultAdmin)
