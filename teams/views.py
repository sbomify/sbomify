from __future__ import annotations

import typing

from sbomify.logging import getLogger

if typing.TYPE_CHECKING:
    from django.http import HttpRequest

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
)
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET

from core.errors import error_response
from core.utils import number_to_random_token, token_to_number
from sboms.models import Component, Product, Project

from .decorators import validate_role_in_current_team
from .forms import (
    InviteUserForm,
    OnboardingComponentForm,
    OnboardingProductForm,
    OnboardingProjectForm,
    TeamForm,
)
from .models import Invitation, Member, Team
from .schemas import BrandingInfo
from .utils import get_user_teams, setup_team_billing_plan

logger = getLogger(__name__)


# view to redirect to /home url
@login_required
def switch_team(request: HttpRequest, team_key: str):
    team = dict(key=team_key, **request.session["user_teams"][team_key])
    request.session["current_team"] = team
    # redirect_to = request.GET.get("next", "core:dashboard")
    redirect_to = "core:dashboard"
    return redirect(redirect_to)


@login_required
def teams_dashboard(request: HttpRequest) -> HttpResponse:
    context = dict(add_team_form=TeamForm())

    if request.method == "POST":
        form = TeamForm(request.POST)
        if form.is_valid():
            team = form.save()

            # Generate team key
            team.key = number_to_random_token(team.pk)
            team.save()

            member = Member(
                user=request.user,
                team=team,
                role="owner",
                is_default_team=False,
            )
            member.save()

            # Set up billing plan for manually created team (no trial, no welcome email)
            setup_team_billing_plan(team, user=None, send_welcome_email=False)

            messages.add_message(
                request,
                messages.SUCCESS,
                f"Workspace {team.name} created successfully",
            )

            # If this is the only team, mark it as default
            user_teams = get_user_teams(request.user)
            if len(user_teams) == 1:
                member.is_default_team = True
                member.save()

            # Update session with new team data
            request.session["user_teams"] = get_user_teams(request.user)

            # Set the newly created team as the current team
            request.session["current_team"] = {
                "key": team.key,
                "name": team.name,
                "role": member.role,
                "is_default_team": member.is_default_team,
                "id": team.id,
            }

            return redirect("teams:teams_dashboard")

    # Get pagination and search parameters
    page = int(request.GET.get("page", 1))
    page_size = int(request.GET.get("page_size", 15))
    search = request.GET.get("search", "").strip()

    # Validate page_size (same limits as other parts of the app)
    page_size = min(max(1, page_size), 100)

    # Use reusable service function to get serializable data with consistent security boundaries
    from .services import get_teams_dashboard_data_with_status

    success, teams_data = get_teams_dashboard_data_with_status(
        request.user, page=page, page_size=page_size, search=search
    )

    if success:
        context["teams_data"] = teams_data["items"]
        context["pagination_meta"] = teams_data["pagination"]
        context["current_page"] = page
        context["page_size"] = page_size
        context["search_query"] = search
        context["page_size_options"] = [10, 15, 25, 50, 100]
    else:
        context["teams_data"] = []
        context["pagination_meta"] = None
        context["current_page"] = 1
        context["page_size"] = page_size
        context["search_query"] = search
        context["page_size_options"] = [10, 15, 25, 50, 100]
        messages.add_message(
            request,
            messages.ERROR,
            "Unable to load workspace data. Please try again.",
        )

    return render(request, "teams/dashboard.html.j2", context)


@login_required
@validate_role_in_current_team(["owner", "admin"])
def team_details(request: HttpRequest, team_key: str):
    """Redirect to team settings for unified interface."""
    return redirect("teams:team_settings", team_key=team_key)


@login_required
@validate_role_in_current_team(["owner"])
def set_default_team(request: HttpRequest, membership_id: int):
    try:
        membership = Member.objects.get(pk=membership_id)
    except Member.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Membership not found"))

    with transaction.atomic():
        # Set is_default_team for all records in membership for the current user to False
        Member.objects.filter(user_id=request.user.id).update(is_default_team=False)
        membership.is_default_team = True
        membership.save()

        messages.add_message(request, messages.INFO, f"Team {membership.team.name} set as the default team")

    request.session["user_teams"] = get_user_teams(request.user)

    return redirect("teams:teams_dashboard")


@login_required
@validate_role_in_current_team(["owner"])
def delete_member(request: HttpRequest, membership_id: int):
    try:
        membership = Member.objects.get(pk=membership_id)
    except Member.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Membership not found"))

    # Verify that there is at least one more owner present for the team
    if membership.role == "owner":
        owner_members = Member.objects.filter(team_id=membership.team_id, role="owner").all()
        if len(owner_members) == 1:
            messages.add_message(
                request,
                messages.WARNING,
                "Cannot delete the only owner of the team. Please assign another owner first.",
            )
            return redirect("teams:team_details", team_key=membership.team.key)

    membership.delete()
    messages.add_message(
        request,
        messages.INFO,
        f"Member {membership.user.username} removed from team {membership.team.name}",
    )

    # If user is deleting his own membership then update session
    if membership.user_id == request.user.id:
        request.session["user_teams"] = get_user_teams(request.user)

    return redirect("teams:team_details", team_key=membership.team.key)


@login_required
@validate_role_in_current_team(["owner"])
def invite(request: HttpRequest, team_key: str) -> HttpResponseForbidden | HttpResponse:
    team_id = token_to_number(team_key)
    context = {"team_key": team_key}

    # Get team for context
    try:
        team = Team.objects.get(id=team_id)
        context["team"] = team
    except Team.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Team not found"))

    if request.method == "POST":
        invite_user_form = InviteUserForm(request.POST)

        # Check user limits before form validation to show as form error
        from .utils import can_add_user_to_team

        can_add, error_message = can_add_user_to_team(team)

        if not can_add:
            # Add form error instead of redirecting
            invite_user_form.add_error(None, error_message)
        elif invite_user_form.is_valid():
            # Check if we already have an invitation and if it's expired or not
            try:
                existing_invitation: Invitation = Invitation.objects.get(
                    email=invite_user_form.cleaned_data["email"], team_id=team_id
                )

                if existing_invitation:
                    if existing_invitation.has_expired:
                        existing_invitation.delete()
                    else:
                        invite_user_form.add_error(
                            "email", f"Invitation already sent to {invite_user_form.cleaned_data['email']}"
                        )
                        context["invite_user_form"] = invite_user_form
                        return render(request, "teams/invite.html.j2", context)

            except Invitation.DoesNotExist:
                pass

            invitation = Invitation(
                team_id=team_id,
                email=invite_user_form.cleaned_data["email"],
                role=invite_user_form.cleaned_data["role"],
            )
            invitation.save()

            email_context = {
                "team": team,
                "invitation": invitation,
                "user": request.user,
                "base_url": settings.APP_BASE_URL,
            }
            send_mail(
                subject=f"Invitation to join {team.name} at sbomify",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[invite_user_form.cleaned_data["email"]],
                message=render_to_string("teams/team_invite_email.txt", email_context),
                html_message=render_to_string("teams/team_invite_email.html.j2", email_context),
            )

            messages.add_message(request, messages.SUCCESS, f"Invite sent to {invite_user_form.cleaned_data['email']}")

            return redirect("teams:team_details", team_key=team_key)

        # If form has errors, fall through to render the form with errors
        context["invite_user_form"] = invite_user_form
    else:
        invite_user_form = InviteUserForm()
        context["invite_user_form"] = invite_user_form

    return render(request, "teams/invite.html.j2", context)


@login_required
@require_GET
def accept_invite(request: HttpRequest, invite_id: int) -> HttpResponseNotFound | HttpResponse:
    logger.info(f"Accepting invitation {invite_id}")
    try:
        invitation = Invitation.objects.get(id=invite_id)
    except Invitation.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Unknown invitation"))

    if invitation.has_expired:
        return error_response(request, HttpResponseForbidden("Invitation has expired"))

    if invitation.email != request.user.email:
        return error_response(request, HttpResponseForbidden("You are not the recipient of this invitation"))

    # Check if we already have a membership
    try:
        existing_membership: Member = Member.objects.get(team_id=invitation.team_id, user_id=request.user.id)
        if existing_membership:
            return error_response(request, HttpResponseForbidden("You are already a member of this team"))

    except Member.DoesNotExist:
        pass

    # Check user limits before accepting invitation
    from .utils import can_add_user_to_team

    can_add, error_message = can_add_user_to_team(invitation.team)
    if not can_add:
        return error_response(request, HttpResponseForbidden(error_message))

    membership = Member(team_id=invitation.team_id, user_id=request.user.id, role=invitation.role)
    membership.save()

    request.session["user_teams"] = get_user_teams(request.user)

    messages.add_message(request, messages.INFO, f"You have joined {invitation.team.name} as {invitation.role}")

    invitation.delete()

    return redirect("core:dashboard")


@login_required
@validate_role_in_current_team(["owner"])
def delete_invite(request: HttpRequest, invitation_id: int):
    try:
        invitation = Invitation.objects.get(pk=invitation_id)
    except Invitation.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Membership not found"))

    messages.add_message(request, messages.INFO, f"Invitation for {invitation.email} deleted")
    invitation.delete()

    return redirect("teams:team_details", team_key=invitation.team.key)


@login_required
def settings_redirect(request: HttpRequest) -> HttpResponse:
    """
    Redirect /workspace/settings/ to the current team's settings page.
    This provides backward compatibility for the old URL structure.
    """
    current_team = request.session.get("current_team")
    if current_team and current_team.get("key"):
        return redirect("teams:team_settings", team_key=current_team["key"])
    else:
        # If no current team, redirect to teams dashboard to select one
        messages.add_message(
            request,
            messages.INFO,
            "Please select a workspace to access its settings.",
        )
        return redirect("teams:teams_dashboard")


@login_required
@validate_role_in_current_team(["owner", "admin"])
def team_settings_redirect(request: HttpRequest, team_key: str) -> HttpResponse:
    """
    Redirect /workspace/{team_key}/settings/ to the unified settings interface.
    This provides backward compatibility for the old URL structure.
    """
    return redirect("teams:team_settings", team_key=team_key)


@login_required
@validate_role_in_current_team(["owner", "admin"])
def team_settings(request: HttpRequest, team_key: str):
    """Redirect to the members page by default"""
    return redirect("teams:team_members", team_key=team_key)


@login_required
@validate_role_in_current_team(["owner"])
def delete_team(request: HttpRequest, team_key: str):
    team_id = token_to_number(team_key)

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Team not found"))

    # Check if this is the user's default team
    try:
        membership = Member.objects.get(user=request.user, team=team)
        if membership.is_default_team:
            messages.add_message(
                request,
                messages.ERROR,
                "Cannot delete the default workspace. Please set another workspace as default first.",
            )
            return error_response(request, HttpResponseBadRequest("Cannot delete the default workspace"))
    except Member.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Membership not found"))

    # Check if this is the user's last team
    user_team_count = Member.objects.filter(user=request.user).count()
    if user_team_count <= 1:
        messages.add_message(
            request,
            messages.ERROR,
            "Cannot delete the default workspace. Please set another workspace as default first.",
        )
        return error_response(request, HttpResponseBadRequest("Cannot delete the default workspace"))

    team_name = team.name
    with transaction.atomic():
        # Members will be automatically deleted due to CASCADE
        team.delete()

    # Update session after team deletion
    request.session["user_teams"] = get_user_teams(request.user)

    messages.add_message(
        request,
        messages.INFO,
        f"Team {team_name} has been deleted",
    )

    return redirect("teams:teams_dashboard")


@login_required
def onboarding_wizard(request: HttpRequest) -> HttpResponse:
    """Handle the onboarding wizard for creating a product, project, and component."""

    # Get the current step from session or query params, defaulting to 'product'
    current_step = request.GET.get("step") or request.session.get("wizard_step", "product")

    # Validate step
    if current_step not in ["product", "project", "component", "complete"]:
        current_step = "product"

    # Initialize context with common data
    context = {
        "current_step": current_step,
        "progress": {
            "product": 0,
            "project": 33,
            "component": 66,
            "complete": 100,
        }[current_step],
    }

    if request.method == "POST":
        if current_step == "product":
            form = OnboardingProductForm(request.POST)
            if form.is_valid():
                try:
                    # Get current team from session
                    team_key = request.session["current_team"]["key"]
                    team = Team.objects.get(key=team_key)

                    # Create the product
                    product = Product.objects.create(name=form.cleaned_data["name"], team=team)
                    # Store product ID in session
                    request.session["wizard_product_id"] = product.id
                    # Move to next step
                    request.session["wizard_step"] = "project"
                    request.session.modified = True  # Explicitly mark session as modified
                    messages.success(request, f"Product '{product.name}' created successfully.")
                    return redirect("teams:onboarding_wizard")
                except IntegrityError:
                    messages.warning(
                        request, f"A product with the name '{form.cleaned_data['name']}' already exists in your team."
                    )
        elif current_step == "project":
            form = OnboardingProjectForm(request.POST)
            if form.is_valid():
                try:
                    # Get current team from session
                    team_key = request.session["current_team"]["key"]
                    team = Team.objects.get(key=team_key)

                    # Get the product from the previous step
                    product_id = request.session.get("wizard_product_id")
                    if not product_id:
                        messages.error(request, "The product from the previous step no longer exists.")
                        request.session["wizard_step"] = "product"
                        return redirect("teams:onboarding_wizard")

                    product = Product.objects.get(id=product_id)

                    # Create the project
                    project = Project.objects.create(name=form.cleaned_data["name"], team=team)

                    # Store project ID in session
                    request.session["wizard_project_id"] = project.id
                    # Move to next step
                    request.session["wizard_step"] = "component"
                    request.session.modified = True  # Explicitly mark session as modified
                    messages.success(request, f"Project '{project.name}' created successfully.")
                    return redirect("teams:onboarding_wizard")
                except IntegrityError:
                    messages.warning(
                        request, f"A project with the name '{form.cleaned_data['name']}' already exists in your team."
                    )
                except Product.DoesNotExist:
                    messages.error(request, "The product from the previous step no longer exists.")
                    request.session["wizard_step"] = "product"
                    return redirect("teams:onboarding_wizard")
        elif current_step == "component":
            form = OnboardingComponentForm(request.POST)
            if form.is_valid():
                try:
                    # Get current team from session
                    team_key = request.session["current_team"]["key"]
                    team = Team.objects.get(key=team_key)

                    # Get the product and project from previous steps
                    product_id = request.session.get("wizard_product_id")
                    project_id = request.session.get("wizard_project_id")
                    if not product_id or not project_id:
                        messages.error(request, "The product or project from previous steps no longer exists.")
                        request.session["wizard_step"] = "product"
                        return redirect("teams:onboarding_wizard")

                    product = Product.objects.get(id=product_id)
                    project = Project.objects.get(id=project_id)

                    # Build component metadata using utility function
                    from sboms.utils import create_default_component_metadata, populate_component_metadata_native_fields

                    component_metadata = create_default_component_metadata(
                        user=request.user, team_id=team.id, custom_metadata=None
                    )

                    # Create the component
                    component = Component.objects.create(
                        name=form.cleaned_data["name"],
                        team=team,
                        metadata=component_metadata,
                    )

                    # Populate native fields with default metadata
                    populate_component_metadata_native_fields(component, request.user, custom_metadata=None)

                    # Link the project to the product
                    product.projects.add(project)

                    # Link the component to the project
                    project.components.add(component)

                    # Mark wizard as completed
                    team.has_completed_wizard = True
                    team.save()

                    # Update session to reflect completed wizard
                    request.session["current_team"]["has_completed_wizard"] = True
                    request.session.modified = True

                    # Clean up session
                    request.session["wizard_step"] = "complete"
                    request.session["wizard_component_id"] = component.id

                    messages.success(request, f"Component '{component.name}' created successfully.")
                    return redirect("teams:onboarding_wizard")
                except IntegrityError:
                    messages.warning(
                        request, f"A component with the name '{form.cleaned_data['name']}' already exists in your team."
                    )
                except (Product.DoesNotExist, Project.DoesNotExist):
                    messages.error(request, "The product or project from previous steps no longer exists.")
                    request.session["wizard_step"] = "product"
                    return redirect("teams:onboarding_wizard")
    else:
        # GET request - show the appropriate form
        if current_step == "product":
            form = OnboardingProductForm()
        elif current_step == "project":
            form = OnboardingProjectForm()
        elif current_step == "component":
            form = OnboardingComponentForm()
        elif current_step == "complete":
            # Show completion page
            context["component_id"] = request.session.get("wizard_component_id")
            # Clean up session
            for key in ["wizard_step", "wizard_product_id", "wizard_project_id", "wizard_component_id"]:
                request.session.pop(key, None)
            return render(request, "core/components/onboarding_wizard.html.j2", context)

    context["form"] = form
    return render(request, "core/components/onboarding_wizard.html.j2", context)


@login_required
@validate_role_in_current_team(["owner", "admin"])
def update_member_role(request: HttpRequest, team_key: str, member_id: int):
    """Update a team member's role."""
    if request.method == "POST":
        try:
            member = Member.objects.get(id=member_id, team__key=team_key)
            new_role = request.POST.get("role")

            if new_role in ["admin", "guest"]:
                member.role = new_role
                member.save()
                messages.add_message(request, messages.SUCCESS, f"Member role updated to {new_role}")
            else:
                messages.add_message(request, messages.ERROR, "Invalid role specified")

        except Member.DoesNotExist:
            messages.add_message(request, messages.ERROR, "Member not found")

    # Redirect back to members tab
    return redirect(reverse("teams:team_settings", args=[team_key]) + "#members")


@login_required
@validate_role_in_current_team(["owner", "admin"])
def remove_member(request: HttpRequest, team_key: str, member_id: int):
    """Remove a member from the team."""
    if request.method == "POST":
        try:
            member = Member.objects.get(id=member_id, team__key=team_key)

            # Don't allow removing the last owner
            if member.role == "owner":
                owner_count = Member.objects.filter(team__key=team_key, role="owner").count()
                if owner_count <= 1:
                    messages.add_message(request, messages.ERROR, "Cannot remove the last owner of the team")
                    return redirect(reverse("teams:team_settings", args=[team_key]) + "#members")

            member.delete()
            messages.add_message(request, messages.SUCCESS, "Member removed successfully")

        except Member.DoesNotExist:
            messages.add_message(request, messages.ERROR, "Member not found")

    # Redirect back to members tab
    return redirect(reverse("teams:team_settings", args=[team_key]) + "#members")


@login_required
@validate_role_in_current_team(["owner", "admin"])
def delete_invitation(request: HttpRequest, team_key: str, invitation_id: int):
    """Delete a pending invitation."""
    if request.method == "POST":
        try:
            invitation = Invitation.objects.get(id=invitation_id, team__key=team_key)
            invitation.delete()
            messages.add_message(request, messages.SUCCESS, "Invitation cancelled successfully")

        except Invitation.DoesNotExist:
            messages.add_message(request, messages.ERROR, "Invitation not found")

    # Redirect back to members tab
    return redirect(reverse("teams:team_settings", args=[team_key]) + "#members")


@login_required
@validate_role_in_current_team(["owner"])
def update_branding(request: HttpRequest, team_key: str):
    """Update team branding settings."""
    if request.method == "POST":
        try:
            team = Team.objects.get(key=team_key)

            # Handle logo removal
            if request.POST.get("action") == "remove_logo":
                if "logo_url" in team.branding_info:
                    del team.branding_info["logo_url"]
                    team.save()
                    messages.add_message(request, messages.SUCCESS, "Logo removed successfully")
                return redirect(reverse("teams:team_settings", args=[team_key]) + "#branding")

            # Update branding info
            branding_info = team.branding_info.copy()

            # Handle file uploads
            if "logo" in request.FILES:
                logo_file = request.FILES["logo"]
                # TODO: Implement file upload to object storage
                # For now, just store a placeholder
                branding_info["logo_url"] = f"/media/team_logos/{team.key}_{logo_file.name}"

            if "icon" in request.FILES:
                icon_file = request.FILES["icon"]
                # TODO: Implement file upload to object storage
                # For now, just store a placeholder
                branding_info["icon_url"] = f"/media/team_icons/{team.key}_{icon_file.name}"

            # Handle icon removal
            if request.POST.get("action") == "remove_icon":
                if "icon_url" in branding_info:
                    del branding_info["icon_url"]

            # Update other branding fields
            if "brand_color" in request.POST:
                branding_info["brand_color"] = request.POST["brand_color"]
            if "accent_color" in request.POST:
                branding_info["accent_color"] = request.POST["accent_color"]
            if "display_name" in request.POST:
                branding_info["display_name"] = request.POST["display_name"]
            if "website_url" in request.POST:
                branding_info["website_url"] = request.POST["website_url"]
            if "description" in request.POST:
                branding_info["description"] = request.POST["description"]
            if "prefer_logo_over_icon" in request.POST:
                branding_info["prefer_logo_over_icon"] = request.POST.get("prefer_logo_over_icon") == "on"

            team.branding_info = branding_info
            team.save()

            messages.add_message(request, messages.SUCCESS, "Branding settings updated successfully")

        except Team.DoesNotExist:
            messages.add_message(request, messages.ERROR, "Team not found")

    # Redirect back to branding tab
    return redirect(reverse("teams:team_settings", args=[team_key]) + "#branding")


@login_required
@validate_role_in_current_team(["owner"])
def update_vulnerability_settings(request: HttpRequest, team_key: str):
    """Update vulnerability scanning settings."""
    if request.method == "POST":
        try:
            from vulnerability_scanning.models import DependencyTrackServer, TeamVulnerabilitySettings

            team = Team.objects.get(key=team_key)

            # Get form data
            vulnerability_provider = request.POST.get("vulnerability_provider", "osv")
            custom_dt_server_id = request.POST.get("custom_dt_server_id", "")

            # Validate provider choice
            if vulnerability_provider not in ["osv", "dependency_track"]:
                messages.add_message(request, messages.ERROR, "Invalid vulnerability provider")
                return redirect("teams:team_integrations", team_key=team_key)

            # Validate billing plan restrictions
            if vulnerability_provider == "dependency_track":
                if not team.billing_plan or team.billing_plan not in ["business", "enterprise"]:
                    messages.add_message(
                        request, messages.ERROR, "Dependency Track is only available for Business and Enterprise plans"
                    )
                    return redirect("teams:team_integrations", team_key=team_key)

            # Handle custom DT server for Enterprise
            custom_dt_server = None
            if custom_dt_server_id and custom_dt_server_id.strip():
                if team.billing_plan != "enterprise":
                    messages.add_message(
                        request,
                        messages.ERROR,
                        "Custom Dependency Track servers are only available for Enterprise plans",
                    )
                    return redirect("teams:team_integrations", team_key=team_key)

                if vulnerability_provider != "dependency_track":
                    messages.add_message(
                        request, messages.ERROR, "Custom DT server can only be used with Dependency Track provider"
                    )
                    return redirect("teams:team_integrations", team_key=team_key)

                try:
                    custom_dt_server = DependencyTrackServer.objects.get(id=custom_dt_server_id, is_active=True)
                except (DependencyTrackServer.DoesNotExist, ValueError):
                    messages.add_message(request, messages.ERROR, "Invalid or inactive Dependency Track server")
                    return redirect("teams:team_integrations", team_key=team_key)

            # Update or create team settings
            team_settings, created = TeamVulnerabilitySettings.objects.update_or_create(
                team=team,
                defaults={"vulnerability_provider": vulnerability_provider, "custom_dt_server": custom_dt_server},
            )

            action = "created" if created else "updated"
            messages.add_message(request, messages.SUCCESS, f"Vulnerability settings {action} successfully")

        except Team.DoesNotExist:
            messages.add_message(request, messages.ERROR, "Team not found")
        except Exception as e:
            messages.add_message(request, messages.ERROR, f"Error updating vulnerability settings: {str(e)}")

    # Redirect back to integrations page
    return redirect("teams:team_integrations", team_key=team_key)


# Individual Team Settings Pages


@login_required
@validate_role_in_current_team(["owner", "admin"])
def team_members(request: HttpRequest, team_key: str):
    """Team members management page"""
    team_id = token_to_number(team_key)

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Team not found"))

    # Get current user's role from session
    current_user_role = request.session.get("current_team", {}).get("role", "guest")

    # Get members and invitations
    members = team.member_set.select_related("user").all()
    invitations = team.invitation_set.all() if current_user_role in ["owner", "admin"] else []

    return render(
        request,
        "teams/team_members.html.j2",
        {
            "team": team,
            "members": members,
            "invitations": invitations,
            "user_role": current_user_role,
        },
    )


@login_required
@validate_role_in_current_team(["owner", "admin"])
def team_branding(request: HttpRequest, team_key: str):
    """Team branding management page"""
    team_id = token_to_number(team_key)

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Team not found"))

    branding_info = BrandingInfo(**team.branding_info)

    # Get current user's role from session
    current_user_role = request.session.get("current_team", {}).get("role", "guest")

    return render(
        request,
        "teams/team_branding.html.j2",
        {
            "team": team,
            "branding_info": branding_info,
            "user_role": current_user_role,
        },
    )


@login_required
@validate_role_in_current_team(["owner"])
def team_integrations(request: HttpRequest, team_key: str):
    """Team integrations management page (owner only)"""
    team_id = token_to_number(team_key)

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Team not found"))

    # Get vulnerability scanning settings
    from vulnerability_scanning.models import DependencyTrackServer, TeamVulnerabilitySettings

    try:
        team_settings = TeamVulnerabilitySettings.objects.get(team=team)
        vulnerability_provider = team_settings.vulnerability_provider
        custom_dt_server_id = str(team_settings.custom_dt_server.id) if team_settings.custom_dt_server else None
    except TeamVulnerabilitySettings.DoesNotExist:
        # Default settings if none exist
        vulnerability_provider = "osv"
        custom_dt_server_id = None

    # Get available DT servers for Enterprise teams
    available_dt_servers = []
    if team.billing_plan == "enterprise":
        # Pass the actual server objects instead of dictionaries to access all fields in templates
        available_dt_servers = list(DependencyTrackServer.objects.all().order_by("priority", "name"))

    vulnerability_settings = {
        "vulnerability_provider": vulnerability_provider,
        "custom_dt_server_id": custom_dt_server_id,
        "available_dt_servers": available_dt_servers,
        "can_use_custom_dt": team.billing_plan == "enterprise",
        "current_plan": team.billing_plan,
    }

    # Mock vulnerability statistics
    vulnerability_stats = {
        "total_scans": 0,
        "total_vulnerabilities": 0,
        "total_components": 0,
        "provider_stats": {},
    }

    # Get current user's role from session
    current_user_role = request.session.get("current_team", {}).get("role", "guest")

    return render(
        request,
        "teams/team_integrations.html.j2",
        {
            "team": team,
            "vulnerability_settings": vulnerability_settings,
            "vulnerability_stats": vulnerability_stats,
            "user_role": current_user_role,
        },
    )


@login_required
@validate_role_in_current_team(["owner"])
def team_billing(request: HttpRequest, team_key: str):
    """Team billing management page (owner only)"""
    team_id = token_to_number(team_key)

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Team not found"))

    # Get current user's role from session
    current_user_role = request.session.get("current_team", {}).get("role", "guest")

    return render(
        request,
        "teams/team_billing.html.j2",
        {
            "team": team,
            "user_role": current_user_role,
        },
    )


@login_required
@validate_role_in_current_team(["owner"])
def team_danger(request: HttpRequest, team_key: str):
    """Team danger zone page (owner only)"""
    team_id = token_to_number(team_key)

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Team not found"))

    # Get current user's role from session
    current_user_role = request.session.get("current_team", {}).get("role", "guest")

    return render(
        request,
        "teams/team_danger.html.j2",
        {
            "team": team,
            "user_role": current_user_role,
        },
    )


@login_required
@validate_role_in_current_team(["owner", "admin"])
def add_dt_server(request: HttpRequest, team_key: str):
    """Add a new DT server for Enterprise workspaces."""
    from vulnerability_scanning.models import DependencyTrackServer

    from .forms import DependencyTrackServerForm

    team_id = token_to_number(team_key)

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Team not found"))

    # Only Enterprise teams can manage custom DT servers
    if team.billing_plan != "enterprise":
        messages.error(request, "Custom DT servers are only available for Enterprise workspaces.")
        return redirect("teams:team_integrations", team_key=team_key)

    if request.method == "POST":
        form = DependencyTrackServerForm(request.POST)
        if form.is_valid():
            # Check for URL uniqueness
            url = form.cleaned_data["url"].rstrip("/")
            if DependencyTrackServer.objects.filter(url=url).exists():
                messages.error(request, "A server with this URL already exists.")
            else:
                try:
                    # Create the server
                    server = DependencyTrackServer.objects.create(
                        name=form.cleaned_data["name"],
                        url=url,
                        api_key=form.cleaned_data["api_key"],
                        priority=form.cleaned_data["priority"],
                        max_concurrent_scans=form.cleaned_data["max_concurrent_scans"],
                        is_active=True,
                        health_status="unknown",
                    )

                    messages.success(request, f"DT server '{server.name}' has been created successfully.")
                    logger.info(f"DT server created by {request.user.email}: {server.name} ({server.id})")
                    return redirect("teams:team_integrations", team_key=team_key)

                except Exception as e:
                    logger.error(f"Error creating DT server: {e}")
                    messages.error(request, "Failed to create server. Please try again.")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = DependencyTrackServerForm()

    # Get current user's role from session
    current_user_role = request.session.get("current_team", {}).get("role", "guest")

    return render(
        request,
        "teams/add_dt_server.html.j2",
        {
            "team": team,
            "form": form,
            "user_role": current_user_role,
        },
    )


@login_required
@validate_role_in_current_team(["owner", "admin"])
def delete_dt_server(request: HttpRequest, team_key: str, server_id: str):
    """Delete a DT server for Enterprise workspaces."""
    from vulnerability_scanning.models import DependencyTrackServer, TeamVulnerabilitySettings

    team_id = token_to_number(team_key)

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return error_response(request, HttpResponseNotFound("Team not found"))

    # Only Enterprise teams can manage custom DT servers
    if team.billing_plan != "enterprise":
        messages.error(request, "Custom DT servers are only available for Enterprise workspaces.")
        return redirect("teams:team_integrations", team_key=team_key)

    try:
        server = DependencyTrackServer.objects.get(id=server_id)
    except (DependencyTrackServer.DoesNotExist, ValueError):
        messages.error(request, "Server not found.")
        return redirect("teams:team_integrations", team_key=team_key)

    # Check if server is currently being used
    if TeamVulnerabilitySettings.objects.filter(custom_dt_server=server).exists():
        messages.error(request, "Cannot delete server that is currently in use by workspaces.")
        return redirect("teams:team_integrations", team_key=team_key)

    # Only handle POST requests - the modal handles the delete confirmation
    if request.method == "POST":
        server_name = server.name
        logger.info(f"DT server deleted by {request.user.email}: {server.name} ({server.id})")
        server.delete()
        messages.success(request, f"DT server '{server_name}' has been deleted successfully.")
        return redirect("teams:team_integrations", team_key=team_key)

    # GET requests should not reach here with the modal pattern, redirect to integrations
    return redirect("teams:team_integrations", team_key=team_key)
