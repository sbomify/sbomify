from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from sbomify.apps.core.errors import error_response
from sbomify.apps.teams.apis import get_team
from sbomify.apps.teams.forms import DeleteInvitationForm, DeleteMemberForm
from sbomify.apps.teams.models import Invitation, Member, Team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.utils import refresh_current_team_session

PLAN_FEATURES = {
    "business": [
        "Advanced SBOM analysis",
        "Advanced vulnerability scanning (every 12 hours)",
        "API access",
        "Priority support",
        "Custom branding",
    ],
    "enterprise": [
        "Everything in Business",
        "Unlimited resources",
        "SSO integration",
        "Advanced security",
        "Dedicated support",
        "Custom integrations",
    ],
}

PLAN_PRICING = {
    "community": {"amount": "$0", "period": "forever"},
    "business": {"amount": "$49", "period": "per month"},
    "enterprise": {"amount": "Custom", "period": "pricing"},
}

PLAN_LIMITS = {
    "max_products": {
        "label": "Products",
        "icon": "box",
    },
    "max_projects": {
        "label": "Projects",
        "icon": "project-diagram",
    },
    "max_components": {
        "label": "Components",
        "icon": "cube",
    },
}


class TeamSettingsView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=team.get("detail", "Unknown error"))
            )

        # Get plan features and pricing based on billing plan
        billing_plan = team.billing_plan or Team.Plan.COMMUNITY
        plan_features = PLAN_FEATURES.get(billing_plan, [])
        plan_pricing = PLAN_PRICING.get(billing_plan, {"amount": "Contact us", "period": ""})
        can_set_private = team.can_set_private
        is_owner = request.session.get("current_team", {}).get("role") == "owner"

        # Process plan limits into structured data
        plan_limits = []
        billing_plan_limits = team.billing_plan_limits or {}
        for limit_key, limit_value in billing_plan_limits.items():
            if limit_key not in PLAN_LIMITS:
                continue

            plan_limits.append(
                {
                    "icon": PLAN_LIMITS[limit_key]["icon"],
                    "label": PLAN_LIMITS[limit_key]["label"],
                    "value": "Unlimited" if limit_value == -1 else str(limit_value),
                }
            )

        return render(
            request,
            "teams/team_settings.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "team": team,
                # Members tab
                "delete_member_form": DeleteMemberForm(),
                "delete_invitation_form": DeleteInvitationForm(),
                # Billing tab
                "plan_features": plan_features,
                "plan_pricing": plan_pricing,
                "plan_limits": plan_limits,
                "can_set_private": can_set_private,
                "is_owner": is_owner,
            },
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        if request.POST.get("visibility_action") == "update":
            return self._update_visibility(request, team_key)

        if request.POST.get("_method") == "DELETE":
            if "member_id" in request.POST:
                return self._delete_member(request, team_key)
            elif "invitation_id" in request.POST:
                return self._delete_invitation(request, team_key)

        messages.error(request, "Invalid request method")
        return redirect("teams:team_settings", team_key=team_key)

    def _delete_member(self, request: HttpRequest, team_key: str) -> HttpResponse:
        from sbomify.apps.teams.utils import remove_member_safely

        form = DeleteMemberForm(request.POST)
        if not form.is_valid():
            messages.error(request, form.errors.as_text())
            return redirect("teams:team_settings", team_key=team_key)

        member_id = form.cleaned_data["member_id"]
        try:
            membership = Member.objects.get(pk=member_id, team__key=team_key)
        except Member.DoesNotExist:
            messages.error(request, "Member not found")
            return redirect("teams:team_settings", team_key=team_key)

        if membership.role == "owner":
            # Check if actor is an admin trying to remove an owner
            actor_membership = Member.objects.filter(user=request.user, team=membership.team).first()
            if actor_membership and actor_membership.role == "admin":
                messages.error(
                    request,
                    "Admins cannot remove workspace owners.",
                )
                return redirect("teams:team_settings", team_key=team_key)

            owners_count = Member.objects.filter(team=membership.team, role="owner").count()
            if owners_count <= 1:
                messages.warning(
                    request,
                    "Cannot delete the only owner of the workspace. Please assign another owner first.",
                )
                return redirect("teams:team_settings", team_key=team_key)

        return remove_member_safely(request, membership)

    def _delete_invitation(self, request: HttpRequest, team_key: str) -> HttpResponse:
        form = DeleteInvitationForm(request.POST)
        if not form.is_valid():
            messages.error(request, form.errors.as_text())
            return redirect("teams:team_settings", team_key=team_key)

        try:
            invitation = Invitation.objects.get(pk=form.cleaned_data["invitation_id"], team__key=team_key)
        except Invitation.DoesNotExist:
            messages.error(request, "Invitation not found")
            return redirect("teams:team_settings", team_key=team_key)

        invitation_email = invitation.email
        invitation.delete()
        messages.info(request, f"Invitation for {invitation_email} deleted")

        return redirect("teams:team_settings", team_key=team_key)

    def _update_visibility(self, request: HttpRequest, team_key: str) -> HttpResponse:
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")
            return redirect("teams:team_settings", team_key=team_key)

        membership = Member.objects.filter(user=request.user, team=team).first()
        if not membership or membership.role != "owner":
            messages.error(request, "Only workspace owners can change visibility")
            return redirect("teams:team_settings", team_key=team_key)

        visibility_values = request.POST.getlist("is_public")
        desired_visibility = self._parse_checkbox_value(visibility_values, default=team.is_public)

        can_set_private = team.can_be_private()
        if desired_visibility is False and not can_set_private:
            messages.error(request, "Disabling the Trust Center is available on Business or Enterprise plans.")
            return redirect("teams:team_settings", team_key=team_key)

        team.is_public = desired_visibility
        team.save()

        refresh_current_team_session(request, team)

        messages.success(request, f"Trust center is now {'public' if team.is_public else 'private'}.")
        return redirect("teams:team_settings", team_key=team_key)

    @staticmethod
    def _parse_checkbox_value(values: list[str], default: bool) -> bool:
        # Hidden field + checkbox submit two values; reverse to prefer the user's checked value
        if not values:
            return default

        for raw in reversed(values):
            val = (raw or "").strip().lower()
            if val in {"true", "1", "on", "yes"}:
                return True
            if val in {"false", "0", "off", "no"}:
                return False

        return default
