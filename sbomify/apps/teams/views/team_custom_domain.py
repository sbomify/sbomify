from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.htmx import htmx_error_response
from sbomify.apps.teams.apis import get_team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin


def get_app_hostname() -> str:
    """Extract hostname from APP_BASE_URL for CNAME instructions.

    Returns only the hostname portion, ignoring any port numbers or paths.
    If APP_BASE_URL is missing a protocol, HTTPS is assumed.
    """
    app_base_url = getattr(settings, "APP_BASE_URL", "")
    if not app_base_url:
        return ""
    # Add protocol if missing for urlparse to work correctly
    if not app_base_url.startswith(("http://", "https://")):
        app_base_url = f"https://{app_base_url}"
    parsed = urlparse(app_base_url)
    return parsed.hostname or ""


def plan_has_custom_domain_access(billing_plan: str | None) -> bool:
    """Check if the billing plan allows custom domain feature."""
    plan_key = (billing_plan or "").strip().lower()
    if not plan_key:
        return False
    try:
        plan = BillingPlan.objects.get(key=plan_key)
        return plan.has_custom_domain_access
    except BillingPlan.DoesNotExist:
        # Fallback for unknown plans - only business/enterprise allowed
        return plan_key in ["business", "enterprise"]


class TeamCustomDomainView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """View for managing workspace custom domain settings."""

    allowed_roles = ["owner"]

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Unknown error"))

        has_custom_domain_access = plan_has_custom_domain_access(team.billing_plan)
        app_hostname = get_app_hostname()

        return render(
            request,
            "teams/team_custom_domain.html.j2",
            {
                "team": team,
                "has_custom_domain_access": has_custom_domain_access,
                "app_hostname": app_hostname,
            },
        )
