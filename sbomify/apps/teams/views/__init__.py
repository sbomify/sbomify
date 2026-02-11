from __future__ import annotations

import typing

from sbomify.logging import getLogger

if typing.TYPE_CHECKING:
    from django.http import HttpRequest

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
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
from sbomify.apps.teams.decorators import validate_role_in_current_team
from sbomify.apps.teams.forms import InviteUserForm
from sbomify.apps.teams.models import (
    Invitation,
    Member,
    Team,
)
from sbomify.apps.teams.queries import count_team_members, count_team_owners
from sbomify.apps.teams.utils import (
    redirect_to_team_settings,
    switch_active_workspace,
    update_user_teams_session,
)

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
from sbomify.apps.teams.views.onboarding_wizard import OnboardingWizardView  # noqa: F401, E402
from sbomify.apps.teams.views.team_branding import TeamBrandingView  # noqa: F401, E402
from sbomify.apps.teams.views.team_custom_domain import TeamCustomDomainView  # noqa: F401, E402
from sbomify.apps.teams.views.team_general import TeamGeneralView  # noqa: F401, E402
from sbomify.apps.teams.views.team_settings import TeamSettingsView  # noqa: F401, E402
from sbomify.apps.teams.views.team_tokens import TeamTokensView  # noqa: F401, E402
from sbomify.apps.teams.views.vulnerability_settings import VulnerabilitySettingsView  # noqa: F401, E402


# view to redirect to /home url
@login_required
def switch_team(request: HttpRequest, team_key: str):
    from django.utils.http import url_has_allowed_host_and_scheme

    team = dict(key=team_key, **request.session["user_teams"][team_key])
    request.session["current_team"] = team

    # Check if user is a guest member of the newly switched workspace
    from sbomify.apps.teams.models import Member

    try:
        Member.objects.get(user=request.user, team__key=team_key, role="guest")
        # Guest members should be redirected to the public workspace page
        redirect_to = reverse("core:workspace_public", kwargs={"workspace_key": team_key})
    except Member.DoesNotExist:
        # Not a guest, check next parameter or default to dashboard
        next_url = request.GET.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts=None):
            redirect_to = next_url
        else:
            redirect_to = reverse("core:dashboard")

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

    # Check if actor is an admin trying to remove an owner or themselves
    # We query the actor's membership explicitly to be safe, although session usually has it.
    actor_membership = Member.objects.filter(user=request.user, team=membership.team).first()
    if actor_membership and actor_membership.role == "admin":
        # Admins cannot remove owners
        if membership.role == "owner":
            messages.add_message(
                request,
                messages.ERROR,
                "Admins cannot remove workspace owners.",
            )
            return redirect("teams:team_settings", team_key=membership.team.key)

        # Admins cannot remove their own membership UNLESS they have pending invites
        if membership.user_id == request.user.id:
            # Check if user has pending invites - if so, allow self-removal
            from sbomify.apps.teams.models import Invitation

            has_pending_invites = Invitation.objects.filter(email=request.user.email).exists()

            if not has_pending_invites:
                from django.http import HttpResponseForbidden

                from sbomify.apps.core.errors import error_response

                return error_response(
                    request,
                    HttpResponseForbidden(
                        "Admins cannot remove their own membership. Only workspace owners can remove members."
                    ),
                )

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
                # Invitation doesn't exist, proceed with creating new one
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
        # If user is not authenticated, store token and redirect to login
        if not request.user.is_authenticated:
            request.session["pending_invitation_token"] = invite_token
            request.session.modified = True
            from urllib.parse import quote

            from django.urls import reverse

            login_url = reverse("core:keycloak_login")
            redirect_url = reverse("teams:accept_invite", kwargs={"invite_token": invite_token})
            return redirect(f"{login_url}?next={quote(redirect_url)}")

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

    # Handle unauthenticated users - redirect to login/signup
    if not request.user.is_authenticated:
        # Store invitation token in session for resumption after login
        request.session["pending_invitation_token"] = invite_token
        request.session.modified = True
        from urllib.parse import quote

        from django.urls import reverse

        login_url = reverse("core:keycloak_login")
        redirect_url = reverse("teams:accept_invite", kwargs={"invite_token": invite_token})
        return redirect(f"{login_url}?next={quote(redirect_url)}")

    # Check if we have a pending invitation token in session (from login redirect)
    # Use session token if available, otherwise use URL token
    pending_token = request.session.pop("pending_invitation_token", None)
    if pending_token:
        # Use the token from session (more reliable after login redirect)
        session_invitation = Invitation.objects.filter(token=pending_token).first()
        if session_invitation:
            invitation = session_invitation
            invite_token = pending_token

    if (request.user.email or "").lower() != invitation.email.lower():
        # Avoid revealing whether an invitation exists for another email
        return error_response(request, HttpResponseNotFound("Unknown invitation"))

    # Check if we already have a membership
    try:
        existing_membership: Member = Member.objects.get(team_id=invitation.team_id, user_id=request.user.id)
        if existing_membership:
            # Update role if invitation role is different
            old_role = existing_membership.role
            role_changed = old_role != invitation.role
            if role_changed:
                existing_membership.role = invitation.role
                existing_membership.save(update_fields=["role"])
                update_user_teams_session(request, request.user)

                # If user was upgraded from guest to admin/owner, remove their access requests
                if old_role == "guest" and invitation.role in ("admin", "owner"):
                    from sbomify.apps.documents.access_models import AccessRequest
                    from sbomify.apps.documents.views.access_requests import _invalidate_access_requests_cache

                    # Delete all access requests for this user in this team
                    AccessRequest.objects.filter(team=invitation.team, user=request.user).delete()
                    # Invalidate cache so the queue updates immediately
                    _invalidate_access_requests_cache(invitation.team)

            switch_active_workspace(request, invitation.team, invitation.role)

            if role_changed:
                messages.add_message(
                    request,
                    messages.SUCCESS,
                    f"Your role in {invitation.team.name} has been updated to {invitation.role}",
                )
            else:
                messages.add_message(
                    request,
                    messages.INFO,
                    f"You have already joined {invitation.team.name} as {invitation.role}",
                )
            invitation.delete()
            return redirect("core:dashboard")

    except Member.DoesNotExist:
        pass

    # Check for company-wide NDA requirement
    company_nda = invitation.team.get_company_nda_document()
    if company_nda:
        # Check if user has already signed the NDA
        from django.contrib.auth import get_user_model

        # Get or create access request for this user
        # Try to get inviter from cache if this is from a trust center invitation
        from django.core.cache import cache

        from sbomify.apps.documents.access_models import AccessRequest

        inviter_id = cache.get(f"invitation_inviter:{invite_token}")
        inviter = None
        if inviter_id:
            try:
                inviter = get_user_model().objects.get(id=inviter_id)
            except get_user_model().DoesNotExist:
                # Inviter user not found in cache, continue without inviter
                pass

        access_request, created = AccessRequest.objects.get_or_create(
            team=invitation.team,
            user=request.user,
            defaults={
                "status": AccessRequest.Status.PENDING,
                "decided_by": inviter,
            },
        )
        # If AccessRequest already exists, update decided_by if not set
        if not created and not access_request.decided_by and inviter:
            access_request.decided_by = inviter
            access_request.save(update_fields=["decided_by"])

        # If NDA is required, user MUST sign it before joining
        # Always redirect to NDA signing page - it will handle approval after signing
        # Store invitation token in session for resumption after NDA signing
        request.session["pending_invitation_token"] = invite_token
        request.session.modified = True
        # Redirect to NDA signing page
        from django.urls import reverse

        return redirect("documents:sign_nda", team_key=invitation.team.key, request_id=access_request.id)

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

    # Create/approve AccessRequest for trust center invitations (only when NO NDA is required)
    # If NDA was required, it would have been handled above and user redirected to sign NDA
    # Get inviter from cache if available
    from django.contrib.auth import get_user_model
    from django.core.cache import cache
    from django.utils import timezone

    User = get_user_model()
    inviter_id = cache.get(f"invitation_inviter:{invite_token}")
    inviter = None
    if inviter_id:
        try:
            inviter = User.objects.get(id=inviter_id)
            # Clean up cache after use
            cache.delete(f"invitation_inviter:{invite_token}")
        except User.DoesNotExist:
            # Inviter user not found, continue without inviter
            pass

    # Create or update AccessRequest and approve it (no NDA required, so auto-approve)
    from sbomify.apps.documents.access_models import AccessRequest

    access_request, created = AccessRequest.objects.get_or_create(
        team=invitation.team,
        user=request.user,
        defaults={
            "status": AccessRequest.Status.APPROVED,
            "decided_by": inviter,
            "decided_at": timezone.now(),
        },
    )
    # If AccessRequest already exists, approve it if still pending
    if not created and access_request.status == AccessRequest.Status.PENDING:
        access_request.status = AccessRequest.Status.APPROVED
        access_request.decided_at = timezone.now()
        if not access_request.decided_by and inviter:
            access_request.decided_by = inviter
        access_request.save()

    # Invalidate cache to refresh the access requests list
    from sbomify.apps.documents.views.access_requests import _invalidate_access_requests_cache

    _invalidate_access_requests_cache(invitation.team)

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
