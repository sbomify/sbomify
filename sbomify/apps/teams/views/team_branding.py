from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.htmx import htmx_error_response, htmx_success_response
from sbomify.apps.teams.apis import (
    get_team,
    get_team_branding,
    update_team_branding,
)
from sbomify.apps.teams.forms import TeamBrandingForm
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.schemas import UpdateTeamBrandingSchema


def get_app_hostname() -> str:
    """Extract hostname from APP_BASE_URL for CNAME instructions."""
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


class TeamBrandingView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Unknown error"))

        status_code, branding_info = get_team_branding(request, team_key)
        if status_code != 200:
            return htmx_error_response(branding_info.get("detail", "Failed to load branding"))

        # Custom domain context
        has_custom_domain_access = plan_has_custom_domain_access(team.billing_plan)
        app_hostname = get_app_hostname()

        return render(
            request,
            "teams/team_branding.html.j2",
            {
                "team": team,
                "branding_info": branding_info,
                "has_custom_domain_access": has_custom_domain_access,
                "app_hostname": app_hostname,
            },
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Unknown error"))

        status_code, branding_info = get_team_branding(request, team_key)
        if status_code != 200:
            return htmx_error_response(branding_info.get("detail", "Failed to load branding"))

        form = TeamBrandingForm(request.POST, request.FILES)
        if not form.is_valid():
            return htmx_error_response(form.errors.as_text())

        payload = UpdateTeamBrandingSchema(
            brand_color=form.cleaned_data.get("brand_color"),
            accent_color=form.cleaned_data.get("accent_color"),
            branding_enabled=form.cleaned_data.get("branding_enabled"),
            icon_pending_deletion=form.cleaned_data.get("icon_pending_deletion", False),
            logo_pending_deletion=form.cleaned_data.get("logo_pending_deletion", False),
        )
        status_code, result = update_team_branding(request, team_key, payload)
        if status_code != 200:
            return htmx_error_response(result.get("detail", "Failed to update branding"))

        return htmx_success_response("Branding updated successfully", triggers={"refreshTeamBranding": True})
