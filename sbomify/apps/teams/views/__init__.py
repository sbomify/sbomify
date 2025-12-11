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

from sbomify.apps.billing.models import BillingPlan
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
from sbomify.apps.teams.utils import get_user_teams, switch_active_workspace  # noqa: F401

log = getLogger(__name__)


def _render_workspace_availability_page(
    request: HttpRequest,
    team: Team,
    invitation: Invitation | None,
    error_message: str,
) -> HttpResponse:
    """Render a friendly status page when the workspace is at capacity."""

    plan_key = team.billing_plan or Team.Plan.COMMUNITY
    plan_label = team.get_billing_plan_display() or getattr(Team.Plan.COMMUNITY, "label", str(Team.Plan.COMMUNITY))

    plan_record = BillingPlan.objects.filter(key=plan_key).first()
    member_limit: int | None = None
    if plan_record:
        plan_label = plan_record.name or plan_label
        member_limit = plan_record.max_users
    elif plan_key == Team.Plan.COMMUNITY:
        member_limit = 1

    owners = (
        Member.objects.filter(team=team, role="owner")
        .select_related("user")
        .order_by("user__first_name", "user__last_name", "user__email")
    )
    owner_contacts = [
        {
            "name": owner.user.get_full_name() or owner.user.email or owner.user.username,
            "email": owner.user.email,
        }
        for owner in owners
    ]

    availability = {
        "team_name": team.display_name,
        "plan_name": plan_label,
        "plan_key": plan_key,
        "member_limit": member_limit,
        "current_members": Member.objects.filter(team=team).count(),
        "owner_contacts": owner_contacts,
    }

    context = {
        "team": team,
        "availability": availability,
        "invitee_email": getattr(invitation, "email", None),
        "error_message": error_message,
        "sales_email": getattr(settings, "ENTERPRISE_SALES_EMAIL", "hello@sbomify.com"),
    }

    return render(
        request,
        "teams/workspace_availability.html.j2",
        context,
        status=HttpResponseForbidden.status_code,
    )


from sbomify.apps.teams.views.contact_profiles import (  # noqa: F401, E402
    ContactProfileFormView,
    ContactProfileView,
)
from sbomify.apps.teams.views.dashboard import WorkspacesDashboardView  # noqa: F401, E402
from sbomify.apps.teams.views.team_branding import TeamBrandingView  # noqa: F401, E402
from sbomify.apps.teams.views.team_settings import TeamSettingsView  # noqa: F401, E402
from sbomify.apps.teams.views.vulnerability_settings import VulnerabilitySettingsView  # noqa: F401, E402


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
@validate_role_in_current_team(["owner", "admin"])
def delete_member(request: HttpRequest, membership_id: int):
    from sbomify.apps.teams.utils import remove_member_safely

    try:
        membership = Member.objects.get(pk=membership_id)
    except Member.DoesNotExist:
        messages.add_message(request, messages.ERROR, "Membership not found")
        # Redirect to dashboard if membership not found, as team key is unavailable.
        return redirect("core:dashboard")

    # Check if actor is an admin trying to remove an owner
    # We query the actor's membership explicitly to be safe, although session usually has it.
    actor_membership = Member.objects.filter(user=request.user, team=membership.team).first()
    if actor_membership and actor_membership.role == "admin" and membership.role == "owner":
        messages.add_message(
            request,
            messages.ERROR,
            "Admins cannot remove workspace owners.",
        )
        return redirect("teams:team_settings", team_key=membership.team.key)

    # Prevent removing the last owner
    if membership.role == "owner":
        owners_count = Member.objects.filter(team=membership.team, role="owner").count()
        if owners_count <= 1:
            messages.add_message(
                request,
                messages.WARNING,
                "Cannot delete the only owner of the team. Please assign another owner first.",
            )
            return redirect("teams:team_details", team_key=membership.team.key)

    return remove_member_safely(request, membership)


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
                message=render_to_string("teams/emails/team_invite_email.txt", email_context),
                html_message=render_to_string("teams/emails/team_invite_email.html.j2", email_context),
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
def accept_invite(request: HttpRequest, invite_token: str) -> HttpResponseNotFound | HttpResponse:
    log.info("Accepting invitation %s", invite_token)

    invitation = Invitation.objects.filter(token=invite_token).first()

    # Backward compatibility for legacy numeric invite links
    if invitation is None and invite_token.isdigit():
        try:
            invitation = Invitation.objects.filter(id=int(invite_token)).first()
        except ValueError:
            pass

    if invitation is None:
        # If the invitation was auto-accepted during login, recover using session data
        auto_accepted_invites = request.session.get("auto_accepted_invites", [])
        matched = next(
            (
                inv
                for inv in auto_accepted_invites
                if inv.get("invitation_token") == invite_token
                or (invite_token.isdigit() and str(inv.get("invitation_id")) == invite_token)
            ),
            None,
        )
        if not matched:
            return error_response(request, HttpResponseNotFound("Unknown invitation"))

        # If membership already exists, treat as success and set session context
        membership = Member.objects.filter(user=request.user, team__key=matched.get("team_key")).first()
        if membership:
            switch_active_workspace(request, membership.team, membership.role)

            messages.add_message(
                request,
                messages.INFO,
                f"You have joined {membership.team.name} as {membership.role}",
            )
            return redirect("core:dashboard")

        return error_response(request, HttpResponseNotFound("Unknown invitation"))

    if invitation.has_expired:
        return error_response(request, HttpResponseForbidden("Invitation has expired"))

    if (request.user.email or "").lower() != invitation.email.lower():
        # Avoid revealing whether an invitation exists for another email
        return error_response(request, HttpResponseNotFound("Unknown invitation"))

    # Check if we already have a membership
    try:
        existing_membership: Member = Member.objects.get(team_id=invitation.team_id, user_id=request.user.id)
        if existing_membership:
            switch_active_workspace(request, invitation.team, existing_membership.role)

            messages.add_message(
                request,
                messages.INFO,
                f"You have already joined {invitation.team.name} as {existing_membership.role}",
            )
            invitation.delete()
            return redirect("core:dashboard")

    except Member.DoesNotExist:
        pass

    # Check user limits before accepting invitation
    from sbomify.apps.teams.utils import can_add_user_to_team

    can_add, error_message = can_add_user_to_team(invitation.team)
    if not can_add:
        return _render_workspace_availability_page(request, invitation.team, invitation, error_message)

    # Set default workspace if user does not have one yet (common for invite-only signups)
    has_default_team = Member.objects.filter(user=request.user, is_default_team=True).exists()
    membership = Member(
        team_id=invitation.team_id,
        user_id=request.user.id,
        role=invitation.role,
        is_default_team=not has_default_team,
    )
    membership.save()

    switch_active_workspace(request, invitation.team, membership.role)

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
