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
    HttpResponseForbidden,
    HttpResponseNotFound,
)
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.utils import token_to_number
from sbomify.apps.sboms.models import Component, Product, Project
from sbomify.apps.teams.decorators import validate_role_in_current_team
from sbomify.apps.teams.forms import (
    InviteUserForm,
    OnboardingCompanyForm,
)
from sbomify.apps.teams.models import (
    ContactEntity,
    ContactProfile,
    ContactProfileContact,
    Invitation,
    Member,
    Team,
    format_workspace_name,
)
from sbomify.apps.teams.queries import count_team_members, count_team_owners
from sbomify.apps.teams.utils import (
    redirect_to_team_settings,
    refresh_current_team_session,
    switch_active_workspace,
    update_user_teams_session,
)  # noqa: F401

log = getLogger(__name__)

# Default URL for SBOM augmentation documentation (can be overridden in settings)
DEFAULT_SBOM_AUGMENTATION_URL = "https://sbomify.com/features/generate-collaborate-analyze/"


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
        "current_members": count_team_members(team.id),
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
from sbomify.apps.teams.views.team_custom_domain import TeamCustomDomainView  # noqa: F401, E402
from sbomify.apps.teams.views.team_general import TeamGeneralView  # noqa: F401, E402
from sbomify.apps.teams.views.team_settings import TeamSettingsView  # noqa: F401, E402
from sbomify.apps.teams.views.team_tokens import TeamTokensView  # noqa: F401, E402
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
        owners_count = count_team_owners(membership.team.id)
        if owners_count <= 1:
            messages.add_message(
                request,
                messages.WARNING,
                "Cannot delete the only owner of the team. Please assign another owner first.",
            )
            return redirect_to_team_settings(membership.team.key, "members")

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

            return redirect_to_team_settings(team_key, "members")

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

    can_add, error_message = can_add_user_to_team(invitation.team, is_joining_via_invite=True)
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

    update_user_teams_session(request, request.user)
    switch_active_workspace(request, invitation.team, invitation.role)

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

    return redirect_to_team_settings(invitation.team.key, "members")


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
    """Single-step onboarding wizard for SBOM identity setup.

    Collects company information, creates a default ContactProfile,
    and auto-creates Product, Project, and Component hierarchy.
    """
    # Import utility functions for component metadata
    from sbomify.apps.sboms.utils import (
        create_default_component_metadata,
        populate_component_metadata_native_fields,
    )

    # Get current team from session
    team_key = request.session["current_team"]["key"]
    team = Team.objects.get(key=team_key)

    # URL for SBOM augmentation deep-dive (configurable via settings)
    sbom_augmentation_url = getattr(settings, "SBOM_AUGMENTATION_URL", DEFAULT_SBOM_AUGMENTATION_URL)

    # Check for completion step
    step = request.GET.get("step")
    if step == "complete":
        context = {
            "current_step": "complete",
            "component_id": request.session.pop("wizard_component_id", None),
            "company_name": request.session.pop("wizard_company_name", ""),
            "sbom_augmentation_url": sbom_augmentation_url,
        }
        return render(request, "core/components/onboarding_wizard.html.j2", context)

    if request.method == "POST":
        form = OnboardingCompanyForm(request.POST)
        if form.is_valid():
            company_name = form.cleaned_data["company_name"]

            # Idempotent design: get_or_create handles reuse of existing resources
            # Check billing limits before creating resources
            from sbomify.apps.core.apis import _check_billing_limits

            # Check if we can create product
            can_create_product, product_error, _ = _check_billing_limits(team.id, "product")
            if not can_create_product:
                messages.error(request, product_error)
                return redirect("teams:onboarding_wizard")

            # Check if we can create project
            can_create_project, project_error, _ = _check_billing_limits(team.id, "project")
            if not can_create_project:
                messages.error(request, project_error)
                return redirect("teams:onboarding_wizard")

            # Check if we can create component
            can_create_component, component_error, _ = _check_billing_limits(team.id, "component")
            if not can_create_component:
                messages.error(request, component_error)
                return redirect("teams:onboarding_wizard")

            try:
                with transaction.atomic():
                    # 1. Get or Create default ContactProfile
                    website_url = form.cleaned_data.get("website")
                    contact_name = form.cleaned_data["contact_name"]
                    # Empty, None, or whitespace-only falls back to user email
                    contact_email = (form.cleaned_data.get("email") or "").strip() or request.user.email

                    # Use get_or_create to ensure we strictly have only 1 default profile
                    contact_profile, created = ContactProfile.objects.get_or_create(
                        team=team, is_default=True, defaults={"name": "Default"}
                    )

                    # 2. Get or Create Entity
                    # Entity name is the company name (company > supplier_name > vendor priority)
                    entity, entity_created = ContactEntity.objects.get_or_create(
                        profile=contact_profile,
                        name=company_name,
                        defaults={
                            "email": contact_email,
                            "website_urls": [website_url] if website_url else [],
                            "is_manufacturer": True,
                            "is_supplier": True,
                        },
                    )

                    # Create the contact person with author role for NTIA compliance
                    # The is_author flag marks this contact as an SBOM author (CycloneDX metadata.authors)
                    # Use get_or_create for idempotency and race condition safety
                    contact, created = ContactProfileContact.objects.get_or_create(
                        entity=entity,
                        name=contact_name,
                        email=contact_email,
                        defaults={"is_author": True},
                    )
                    # If contact already exists but isn't marked as author, update it
                    if not created and not contact.is_author:
                        contact.is_author = True
                        contact.save(update_fields=["is_author"])

                    # 2. Auto-create hierarchy with SBOM component type
                    # Set visibility based on billing plan: community plans must be public
                    is_public = not team.can_be_private()
                    product, _ = Product.objects.get_or_create(
                        name=company_name, team=team, defaults={"is_public": is_public}
                    )
                    project, _ = Project.objects.get_or_create(
                        name="Main Project", team=team, defaults={"is_public": is_public}
                    )

                    component_metadata = create_default_component_metadata(
                        user=request.user, team_id=team.id, custom_metadata=None
                    )

                    component, component_created = Component.objects.get_or_create(
                        name="Main Component",
                        team=team,
                        defaults={
                            "component_type": Component.ComponentType.SBOM,
                            "metadata": component_metadata,
                            "is_public": is_public,
                        },
                    )

                    if component_created:
                        # Populate native fields with default metadata
                        populate_component_metadata_native_fields(component, request.user, custom_metadata=None)
                        # Save the component to persist contact_profile and other metadata fields
                        component.save()

                    # Link hierarchy: product -> project -> component
                    product.projects.add(project)
                    project.components.add(component)

                    # 3. Update workspace name and mark wizard as completed
                    team.name = format_workspace_name(company_name)
                    team.has_completed_wizard = True
                    team.save()

                    # 4. Update session - refresh user_teams to pick up new team state
                    update_user_teams_session(request, request.user)

                    # Refresh current_team with all the latest team data (including id)
                    refresh_current_team_session(request, team)

                    # Store wizard completion data for the success page
                    request.session["wizard_component_id"] = component.id
                    request.session["wizard_company_name"] = company_name
                    request.session.modified = True

                messages.success(request, "Your SBOM identity has been set up!")
                return redirect(f"{reverse('teams:onboarding_wizard')}?step=complete")
            except IntegrityError as e:
                # Fallback for race conditions or unexpected constraint violations
                log.warning(f"IntegrityError during onboarding for team {team.key}, company_name='{company_name}': {e}")
                messages.warning(
                    request,
                    "Setup could not be completed due to a conflict. Please try again or contact support.",
                )
    else:
        # GET request - show the form with pre-filled data
        initial = {"email": request.user.email}

        # Pre-fill contact name from user's full name if available
        full_name = request.user.get_full_name()
        if full_name:
            initial["contact_name"] = full_name

        form = OnboardingCompanyForm(initial=initial)

    context = {
        "form": form,
        "current_step": "setup",
        "sbom_augmentation_url": sbom_augmentation_url,
    }
    return render(request, "core/components/onboarding_wizard.html.j2", context)
