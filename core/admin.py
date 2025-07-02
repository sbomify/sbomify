import logging
from functools import wraps

from allauth.socialaccount.models import SocialAccount
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.template.response import TemplateResponse
from django.urls import path
from django.utils.html import format_html

from sboms.models import SBOM  # SBOM still lives in sboms app
from teams.models import Member, Team

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
                stats = {
                    "users": User.objects.count(),
                    "teams": Team.objects.count(),
                    "products": Product.objects.count(),
                    "projects": Project.objects.count(),
                    "components": Component.objects.count(),
                    "sboms": SBOM.objects.count(),
                    "users_per_team": list(
                        Team.objects.annotate(user_count=Count("members")).values("name", "user_count")
                    ),
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
                }

        return stats

    @admin_dashboard_required
    def dashboard_view(self, request):
        """View for the admin dashboard."""
        context = {
            **self.each_context(request),
            "title": "System Dashboard",
            "stats": self.get_dashboard_stats(),
            "app_label": "core",
            "has_permission": True,
        }
        return TemplateResponse(request, "admin/dashboard.html", context)

    def get_social_accounts(self, obj):
        accounts = obj.socialaccount_set.all()
        return format_html("<br>".join(f"{account.provider}: {account.uid}" for account in accounts))

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
        """Get email verification status from Keycloak.

        Checks both Keycloak and social login providers (GitHub/Google) which
        may have different verification statuses.
        """
        auth = obj.socialaccount_set.first()
        if not auth:
            return format_html('<span style="color: #666;">No social account</span>')

        # Check Keycloak verification
        if auth.provider == "keycloak" and auth.extra_data:
            verified = auth.extra_data.get("email_verified", False)
            return format_html(
                '<span style="color: {};">{}</span>',
                "#28a745" if verified else "#dc3545",
                "Verified" if verified else "Not Verified",
            )

        # For other providers, check their specific verification field
        if auth.provider == "github":
            verified = auth.extra_data.get("email_verified", False)
        elif auth.provider == "google":
            verified = auth.extra_data.get("verified_email", False)
        else:
            verified = False

        return format_html(
            '<span style="color: {};">{}</span>',
            "#28a745" if verified else "#dc3545",
            "Verified" if verified else "Not Verified",
        )

    def social_accounts(self, obj):
        """Display social accounts for the user."""
        social_auths = SocialAccount.objects.filter(user=obj)
        if not social_auths:
            return format_html('<span style="color: #666;">None</span>')

        accounts = []
        for auth in social_auths:
            provider = auth.provider.capitalize()
            uid = auth.uid
            verified = "✓" if auth.extra_data.get("email_verified", False) else "✗"
            accounts.append(f"{provider}: {uid} {verified}")

        return format_html("<br>".join(accounts))


# Create custom admin site
admin_site = DashboardView(name="admin")

# Register all models with our custom admin site
admin_site.register(User, CustomUserAdmin)
admin_site.register(Team)
admin_site.register(Member)
admin_site.register(Product)
admin_site.register(Project)
admin_site.register(Component)
admin_site.register(SBOM)
