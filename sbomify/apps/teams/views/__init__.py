from __future__ import annotations

import typing

from sbomify.logging import getLogger

if typing.TYPE_CHECKING:
    from django.http import HttpRequest

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import IntegrityError
from django.http import (
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseNotFound,
)
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.utils import token_to_number
from sbomify.apps.sboms.models import Component, Product, Project
from sbomify.apps.teams.decorators import validate_role_in_current_team
from sbomify.apps.teams.forms import (
    InviteUserForm,
    OnboardingComponentForm,
    OnboardingProductForm,
    OnboardingProjectForm,
)
from sbomify.apps.teams.models import Invitation, Member, Team
from sbomify.apps.teams.utils import get_user_teams

log = getLogger(__name__)

from sbomify.apps.teams.views.dashboard import TeamsDashboardView  # noqa: F401, E402
from sbomify.apps.teams.views.team_settings import TeamSettingsView  # noqa: F401, E402


# view to redirect to /home url
@login_required
def switch_team(request: HttpRequest, team_key: str):
    team = dict(key=team_key, **request.session["user_teams"][team_key])
    request.session["current_team"] = team
    # redirect_to = request.GET.get("next", "core:dashboard")
    redirect_to = "core:dashboard"
    return redirect(redirect_to)


@login_required
@validate_role_in_current_team(["owner", "admin"])
def team_details(request: HttpRequest, team_key: str):
    """Redirect to team settings for unified interface."""
    return redirect("teams:team_settings", team_key=team_key)


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
        from sbomify.apps.teams.utils import can_add_user_to_team

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
    log.info(f"Accepting invitation {invite_id}")
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
    from sbomify.apps.teams.utils import can_add_user_to_team

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
                    from sbomify.apps.sboms.utils import (
                        create_default_component_metadata,
                        populate_component_metadata_native_fields,
                    )

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
