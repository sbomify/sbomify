from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.stripe_sync import sync_subscription_from_stripe
from sbomify.apps.billing.team_pricing_service import TeamPricingService
from sbomify.apps.core.errors import error_response
from sbomify.apps.teams.apis import get_team, list_contact_profiles
from sbomify.apps.teams.forms import DeleteInvitationForm, DeleteMemberForm
from sbomify.apps.teams.models import Invitation, Member, Team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.utils import refresh_current_team_session
from sbomify.logging import getLogger

logger = getLogger(__name__)

PLAN_FEATURES = {
    "community": [
        "Unlimited SBOMs",
        "Unlimited products & projects",
        "All data is public",
        "Weekly vulnerability scans",
        "Community support",
        "API access",
        "Workspace management",
        "Public Trust Center",
        "Custom branding (logo & colors)",
    ],
    "business": [
        "Everything in Community",
        "Private components/projects/products",
        "NTIA Minimum Elements check",
        "Advanced vulnerability scanning (every 12 hours)",
        "Product identifiers (SKUs/barcodes)",
        "Priority support",
        "Workspace management",
        "Public Trust Center",
        "Custom domain for Trust Center",
        "Custom branding (logo & colors)",
    ],
    "enterprise": [
        "Everything in Business",
        "Unlimited users",
        "Custom Dependency Track servers",
        "Dedicated support",
        "Custom integrations",
        "SLA guarantee",
        "Advanced security",
        "Custom deployment options",
        "Public Trust Center",
        "Custom domain for Trust Center",
        "Advanced custom branding (logo, colors, themes)",
    ],
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


@method_decorator(never_cache, name="dispatch")
class TeamSettingsView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    allowed_roles = ["owner", "admin"]

    def _redirect_with_tab(self, request: HttpRequest, team_key: str) -> HttpResponse:
        """Redirect to team settings, preserving the active tab if provided."""
        from sbomify.apps.teams.utils import redirect_to_team_settings

        active_tab = request.POST.get("active_tab", "")
        return redirect_to_team_settings(team_key, active_tab if active_tab else None)

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        status_code, team = get_team(request, team_key)
        if status_code != 200:
            return error_response(
                request, HttpResponse(status=status_code, content=team.get("detail", "Unknown error"))
            )

        # Sync subscription data from Stripe before displaying billing info
        try:
            team_obj = Team.objects.get(key=team_key)
            sync_subscription_from_stripe(team_obj)
            # Refresh team data after sync
            team_obj.refresh_from_db()
        except Team.DoesNotExist:
            team_obj = None

        # Get plan features and pricing based on billing plan
        billing_plan = team.billing_plan or Team.Plan.COMMUNITY
        plan_features = PLAN_FEATURES.get(billing_plan, [])

        # Use pricing service to calculate plan pricing and limits
        pricing_service = TeamPricingService()

        # Fetch billing plan object once for reuse
        try:
            billing_plan_obj = BillingPlan.objects.get(key=billing_plan)
        except BillingPlan.DoesNotExist:
            billing_plan_obj = None

        # Get pricing information
        plan_pricing = pricing_service.get_plan_pricing(team, billing_plan_obj)

        # Get plan limits
        plan_limits = pricing_service.get_plan_limits(team, billing_plan_obj)

        # Get actual Team model instance to access helper properties and enrich context
        # (The 'team' from get_team is a Pydantic schema which lacks these properties)
        # team_obj was already fetched above for sync, reuse it
        if not team_obj:
            try:
                team_obj = Team.objects.get(key=team_key)
            except Team.DoesNotExist:
                team_obj = None

        # Convert Pydantic model to dict so we can inject properties
        # .dict() is generic for Pydantic v1/v2, .model_dump() is v2
        # leveraging getattr to support both or verify version. assuming .dict() or simply vars() won't work on Pydantic
        # Using model_dump() if available (Pydantic V2) or dict() (V1)
        if team_obj:
            try:
                team_data = team.dict() if hasattr(team, "dict") else team.model_dump()
            except AttributeError:
                # Fallback if team doesn't have dict or model_dump
                team_data = team.model_dump() if hasattr(team, "model_dump") else vars(team)

            # Inject properties used by global banners
            team_data["is_in_grace_period"] = team_obj.is_in_grace_period
            team_data["is_payment_restricted"] = team_obj.is_payment_restricted
        else:
            # Fallback if team_obj not found
            team_data = team  # Use schema as-is

        can_set_private = team_data.get("can_set_private") if isinstance(team_data, dict) else team.can_set_private
        is_owner = request.session.get("current_team", {}).get("role") == "owner"

        # Get branding info for trust center settings
        branding_info = team_obj.branding_info if team_obj else {}

        # Fetch contact profiles for the settings tab
        _, profiles = list_contact_profiles(request, team_key)

        return render(
            request,
            "teams/team_settings.html.j2",
            {
                "APP_BASE_URL": settings.APP_BASE_URL,
                "team": team_data,
                "team_obj": team_obj,  # Pass actual model in case specific valid/function call is lower down
                # Members tab
                "delete_member_form": DeleteMemberForm(),
                "delete_invitation_form": DeleteInvitationForm(),
                # Billing tab
                "plan_features": plan_features,
                "all_plan_features": PLAN_FEATURES,
                "plan_pricing": plan_pricing,
                "plan_limits": plan_limits,
                "can_set_private": can_set_private,
                "is_owner": is_owner,
                # Trust center settings
                "branding_info": branding_info,
                # Contact Profiles tab
                "profiles": profiles,
            },
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        if request.POST.get("visibility_action") == "update":
            return self._update_visibility(request, team_key)

        if request.POST.get("trust_center_description_action") == "update":
            return self._update_trust_center_description(request, team_key)

        if request.POST.get("tea_action") == "update":
            return self._update_tea_enabled(request, team_key)

        if request.POST.get("_method") == "DELETE":
            if "member_id" in request.POST:
                return self._delete_member(request, team_key)
            elif "invitation_id" in request.POST:
                return self._delete_invitation(request, team_key)

        messages.error(request, "Invalid request method")
        return self._redirect_with_tab(request, team_key)

    def _delete_member(self, request: HttpRequest, team_key: str) -> HttpResponse:
        from sbomify.apps.teams.utils import remove_member_safely

        form = DeleteMemberForm(request.POST)
        if not form.is_valid():
            messages.error(request, form.errors.as_text())
            return self._redirect_with_tab(request, team_key)

        member_id = form.cleaned_data["member_id"]
        try:
            membership = Member.objects.get(pk=member_id, team__key=team_key)
        except Member.DoesNotExist:
            messages.error(request, "Member not found")
            return self._redirect_with_tab(request, team_key)

        if membership.role == "owner":
            # Check if actor is an admin trying to remove an owner
            actor_membership = Member.objects.filter(user=request.user, team=membership.team).first()
            if actor_membership and actor_membership.role == "admin":
                messages.error(
                    request,
                    "Admins cannot remove workspace owners.",
                )
                return self._redirect_with_tab(request, team_key)

            owners_count = Member.objects.filter(team=membership.team, role="owner").count()
            if owners_count <= 1:
                messages.warning(
                    request,
                    "Cannot delete the only owner of the workspace. Please assign another owner first.",
                )
                return self._redirect_with_tab(request, team_key)

        active_tab = request.POST.get("active_tab", "")
        return remove_member_safely(request, membership, active_tab=active_tab if active_tab else None)

    def _delete_invitation(self, request: HttpRequest, team_key: str) -> HttpResponse:
        form = DeleteInvitationForm(request.POST)
        if not form.is_valid():
            messages.error(request, form.errors.as_text())
            return self._redirect_with_tab(request, team_key)

        try:
            invitation = Invitation.objects.get(pk=form.cleaned_data["invitation_id"], team__key=team_key)
        except Invitation.DoesNotExist:
            messages.error(request, "Invitation not found")
            return self._redirect_with_tab(request, team_key)

        invitation_email = invitation.email
        invitation.delete()
        messages.info(request, f"Invitation for {invitation_email} deleted")

        return self._redirect_with_tab(request, team_key)

    def _update_visibility(self, request: HttpRequest, team_key: str) -> HttpResponse:
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")
            return self._redirect_with_tab(request, team_key)

        membership = Member.objects.filter(user=request.user, team=team).first()
        if not membership or membership.role != "owner":
            messages.error(request, "Only workspace owners can change visibility")
            return self._redirect_with_tab(request, team_key)

        visibility_values = request.POST.getlist("is_public")
        desired_visibility = self._parse_checkbox_value(visibility_values, default=team.is_public)

        can_set_private = team.can_be_private()
        if desired_visibility is False and not can_set_private:
            messages.error(request, "Disabling the Trust Center is available on Business or Enterprise plans.")
            return self._redirect_with_tab(request, team_key)

        team.is_public = desired_visibility
        team.save()

        refresh_current_team_session(request, team)

        messages.success(request, f"Trust center is now {'public' if team.is_public else 'private'}.")
        return self._redirect_with_tab(request, team_key)

    def _update_trust_center_description(self, request: HttpRequest, team_key: str) -> HttpResponse:
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")
            return self._redirect_with_tab(request, team_key)

        membership = Member.objects.filter(user=request.user, team=team).first()
        if not membership or membership.role != "owner":
            messages.error(request, "Only workspace owners can change the trust center description")
            return self._redirect_with_tab(request, team_key)

        description = request.POST.get("trust_center_description", "").strip()

        # Validate length
        if len(description) > 500:
            messages.error(request, "Description must be 500 characters or less")
            return self._redirect_with_tab(request, team_key)

        # Update branding_info with new description
        branding_info = team.branding_info or {}
        branding_info["trust_center_description"] = description
        team.branding_info = branding_info
        team.save()

        if description:
            messages.success(request, "Trust center description updated.")
        else:
            messages.success(request, "Trust center description cleared. Using default description.")
        return self._redirect_with_tab(request, team_key)

    def _update_tea_enabled(self, request: HttpRequest, team_key: str) -> HttpResponse:
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            messages.error(request, "Workspace not found")
            return self._redirect_with_tab(request, team_key)

        membership = Member.objects.filter(user=request.user, team=team).first()
        if not membership or membership.role != "owner":
            messages.error(request, "Only workspace owners can change TEA settings")
            return self._redirect_with_tab(request, team_key)

        tea_values = request.POST.getlist("tea_enabled")
        desired_tea_enabled = self._parse_checkbox_value(tea_values, default=team.tea_enabled)

        team.tea_enabled = desired_tea_enabled
        team.save()

        refresh_current_team_session(request, team)

        messages.success(request, f"Transparency Exchange API is now {'enabled' if team.tea_enabled else 'disabled'}.")
        return self._redirect_with_tab(request, team_key)

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
