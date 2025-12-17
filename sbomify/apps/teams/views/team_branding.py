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
    """Extract hostname from APP_BASE_URL setting."""
    app_base_url = getattr(settings, "APP_BASE_URL", "").strip()
    if not app_base_url:
        return ""

    # Add protocol if missing
    if not app_base_url.startswith(("http://", "https://")):
        app_base_url = f"http://{app_base_url}"

    try:
        parsed = urlparse(app_base_url)
        hostname = parsed.hostname or ""
        # Handle localhost case
        if hostname == "localhost":
            return "localhost"
        return hostname
    except (ValueError, AttributeError):
        return ""


def plan_has_custom_domain_access(plan: str | None) -> bool:
    """Check if a billing plan has custom domain access."""
    if not plan:
        return False

    plan_str = str(plan).strip().lower()

    # Business and Enterprise plans have access
    if plan_str in ("business", "enterprise"):
        return True

    # Check if it's a BillingPlan in the database with custom domain access
    try:
        billing_plan = BillingPlan.objects.get(key=plan_str)
        return getattr(billing_plan, "has_custom_domain_access", False)
    except BillingPlan.DoesNotExist:
        return False


class TeamBrandingView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return htmx_error_response(team.get("detail", "Unknown error"))

        status_code, branding_info = get_team_branding(request, team_key)
        if status_code != 200:
            return htmx_error_response(branding_info.get("detail", "Failed to load branding"))

        # Prepare custom domain context for the template/JavaScript
        has_access = plan_has_custom_domain_access(team.billing_plan)
        custom_domain = team.custom_domain or ""
        is_validated = team.custom_domain_validated if custom_domain else False
        last_checked_at = team.custom_domain_last_checked_at.isoformat() if team.custom_domain_last_checked_at else ""

        custom_domain_config = {
            "teamKey": team.key,
            "initialDomain": custom_domain,
            "isValidated": is_validated,
            "lastCheckedAt": last_checked_at,
            "hasAccess": has_access,
        }

        return render(
            request,
            "teams/team_branding.html.j2",
            {
                "team": team,
                "branding_info": branding_info,
                "custom_domain_config": custom_domain_config,
                "app_hostname": get_app_hostname(),
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
