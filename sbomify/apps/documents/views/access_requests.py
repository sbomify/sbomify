import hashlib
import logging
from typing import Any, cast
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseBase
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache

from sbomify.apps.core.authz import ADMINISTER
from sbomify.apps.core.errors import error_response
from sbomify.apps.core.models import User
from sbomify.apps.core.object_store import StorageClient
from sbomify.apps.core.posthog_service import capture_for_request
from sbomify.apps.core.url_utils import get_base_url
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.documents.services.access_emails import (
    notify_access_approved,
    notify_access_rejected,
    notify_access_revoked,
    notify_admins_of_access_request,
)
from sbomify.apps.documents.services.access_requests import (
    ANY_MEMBER_ROLES,
    approve_request,
    dismiss_access_request_notification_if_no_pending,
    invalidate_access_requests_cache,
    pending_access_requests,
    record_nda_signature,
    reject_request,
    request_access,
    revoke_request,
)
from sbomify.apps.teams.branding import build_branding_context
from sbomify.apps.teams.models import Invitation, Member, Team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.queries import invitation_email
from sbomify.apps.teams.utils import (
    switch_active_workspace,
    update_user_teams_session,
    user_seat,
)

logger = logging.getLogger(__name__)


def user_has_signed_current_nda(user: User, team: Team) -> bool:
    """Check if user has signed the current company-wide NDA version.

    DEPRECATED: Use _user_has_signed_current_nda from core.services.access_control instead.
    This function is kept for backward compatibility.

    Args:
        user: User instance to check
        team: Team instance to check NDA for

    Returns:
        True if user has signed the current NDA version, False otherwise.
        Returns True if no NDA is required.
    """
    from sbomify.apps.core.services.access_control import _user_has_signed_current_nda

    result: bool = _user_has_signed_current_nda(user, team)
    return result


def _get_approved_access_requests(team: Team) -> QuerySet[AccessRequest]:
    """Get approved access requests for a team.

    Args:
        team: Team instance to get requests for

    Returns:
        QuerySet of approved AccessRequest objects with optimized prefetching
    """
    return (
        AccessRequest.objects.filter(team=team, status=AccessRequest.Status.APPROVED)
        .select_related("user", "decided_by")
        .prefetch_related("nda_signatures__nda_document")
        .order_by("-decided_at")
    )


def _get_rejected_access_requests(team: Team) -> QuerySet[AccessRequest]:
    """Get rejected access requests for a team.

    Args:
        team: Team instance to get requests for

    Returns:
        QuerySet of rejected AccessRequest objects with optimized prefetching
    """
    return (
        AccessRequest.objects.filter(team=team, status=AccessRequest.Status.REJECTED)
        .select_related("user", "decided_by")
        .order_by("-decided_at")
    )


def _annotate_nda_signature_status(requests: list[AccessRequest], company_nda: Document | None) -> None:
    """Annotate access requests with current NDA signature status.

    Args:
        requests: QuerySet or list of AccessRequest objects
        company_nda: Current company NDA document or None
    """
    if not requests:
        return

    if company_nda:
        # Prefetch all signatures for these requests in one query
        request_ids = [req.id for req in requests]
        current_signatures = set(
            NDASignature.objects.live()
            .filter(access_request_id__in=request_ids, nda_document=company_nda)
            .values_list("access_request_id", flat=True)
        )
        for req in requests:
            req.has_current_nda_signature = req.id in current_signatures  # type: ignore[attr-defined]
    else:
        # No NDA required, so signature status doesn't matter
        for req in requests:
            req.has_current_nda_signature = True  # type: ignore[attr-defined]


def _back(team_key: str, active_tab: str) -> HttpResponse:
    """Where a queue action lands without htmx: the trust-center tab, told to refresh, or the queue."""
    if active_tab == "trust-center":
        response: HttpResponse = redirect(
            reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}"
        )
        response["HX-Trigger"] = "refreshAccessRequests"
        return response
    return redirect("documents:access_request_queue", team_key=team_key)


def _queue_response(request: HttpRequest, team: Team, hx_trigger: str | None = None) -> HttpResponse:
    """The queue section: pending, approved and rejected requests, and pending invitations."""
    company_nda = team.get_company_nda_document()
    pending_requests = list(pending_access_requests(team))
    approved_requests = list(_get_approved_access_requests(team))
    rejected_requests = list(_get_rejected_access_requests(team))

    # Annotate requests with current NDA signature status
    _annotate_nda_signature_status(pending_requests, company_nda)
    _annotate_nda_signature_status(approved_requests, company_nda)

    # Try to get inviter info from cache for each invitation
    # Fallback: check AccessRequest if user already exists
    invitations_with_inviter = []
    for invitation in Invitation.objects.filter(team=team).order_by("-created_at"):
        inviter_email = None
        cache_key = f"invitation_inviter:{invitation.token}"
        inviter_id = cache.get(cache_key)
        if inviter_id:
            try:
                inviter = User.objects.get(id=inviter_id)
                inviter_email = inviter.email
            except User.DoesNotExist:
                # Inviter user not found in cache, continue without inviter_email
                pass

        # Fallback: check if user exists and has an AccessRequest with decided_by set
        if not inviter_email:
            try:
                invited_user = User.objects.get(email__iexact=invitation.email)
                access_request = AccessRequest.objects.filter(
                    team=team, user=invited_user, decided_by__isnull=False
                ).first()
                if access_request and access_request.decided_by:
                    inviter_email = access_request.decided_by.email
            except (User.DoesNotExist, User.MultipleObjectsReturned):
                # Invited user not found, continue without inviter_email
                pass

        invitations_with_inviter.append(
            {
                "invitation": invitation,
                "inviter_email": inviter_email,
            }
        )

    response = render(
        request,
        "documents/access_request_queue_content.html.j2",
        {
            "team": team,
            "pending_requests": pending_requests,
            "approved_requests": approved_requests,
            "rejected_requests": rejected_requests,
            "pending_invitations": invitations_with_inviter,
        },
    )
    if hx_trigger:
        response["HX-Trigger"] = hx_trigger
    return response


@method_decorator(never_cache, name="dispatch")
class AccessRequestView(View):
    """View for creating access requests (supports both authenticated and unauthenticated users)."""

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        """Show access request form."""
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            return error_response(request, HttpResponse(status=404, content="Team not found"))

        # Redirect unauthenticated users to login with redirect back to this page
        if not request.user.is_authenticated:
            login_url = reverse("core:keycloak_login")
            redirect_url = reverse("documents:request_access", kwargs={"team_key": team_key})
            return redirect(f"{login_url}?next={quote(redirect_url)}")

        # Check if user already has access
        if request.user.is_authenticated:
            try:
                member = Member.objects.get(team=team, user=request.user)
                if member.role in ANY_MEMBER_ROLES:
                    messages.info(request, "You already have access to gated components in this workspace.")
                    return redirect("core:workspace_public", workspace_key=team_key)
            except Member.DoesNotExist:
                # User is not a member, continue to check for access request
                pass

            # Check for approved access request
            approved_request = AccessRequest.objects.filter(
                team=team, user=request.user, status=AccessRequest.Status.APPROVED
            ).first()
            if approved_request:
                messages.info(request, "You already have access to gated components in this workspace.")
                return redirect("core:workspace_public", workspace_key=team_key)

        # Check if there's a pending request
        if request.user.is_authenticated:
            pending_request = AccessRequest.objects.filter(
                team=team, user=request.user, status=AccessRequest.Status.PENDING
            ).first()
            if pending_request:
                messages.info(request, "Your access request is pending approval.")
                return redirect("core:workspace_public", workspace_key=team_key)

        # A requester whose last request was rejected otherwise lands on a blank
        # form with no sign anything happened; say so, and let them re-request.
        was_rejected = AccessRequest.objects.filter(
            team=team, user=request.user, status=AccessRequest.Status.REJECTED
        ).exists()

        # Always check for company-wide NDA - if it exists, always require signing
        company_nda = team.get_company_nda_document()
        requires_nda = company_nda is not None

        # Build branding context for the template
        brand = build_branding_context(team)

        return render(
            request,
            "documents/request_access.html.j2",
            {
                "team": team,
                "brand": brand,
                "company_nda": company_nda,
                "requires_nda": requires_nda,
                "was_rejected": was_rejected,
                "user": request.user if request.user.is_authenticated else None,
            },
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        """Create access request."""
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            return error_response(request, HttpResponse(status=404, content="Team not found"))

        # The same rule as GET: the requester signs in and asks for themselves.
        # A posted email address is not an identity.
        if not request.user.is_authenticated:
            login_url = reverse("core:keycloak_login")
            redirect_url = reverse("documents:request_access", kwargs={"team_key": team_key})
            return redirect(f"{login_url}?next={quote(redirect_url)}")
        user = request.user

        # Check if user already has access
        try:
            member = Member.objects.get(team=team, user=user)
            if member.role in ANY_MEMBER_ROLES:
                messages.info(request, "You already have access to gated components in this workspace.")
                return redirect("core:workspace_public", workspace_key=team_key)
        except Member.DoesNotExist:
            # User is not a member, continue to check for access request
            pass

        # Check for existing approved request
        approved_request = AccessRequest.objects.filter(
            team=team, user=user, status=AccessRequest.Status.APPROVED
        ).first()
        if approved_request:
            messages.info(request, "You already have access to gated components in this workspace.")
            return redirect("core:workspace_public", workspace_key=team_key)

        # Always check for company-wide NDA - if it exists, always require signing
        company_nda = team.get_company_nda_document()
        requires_nda = company_nda is not None

        # Check for pending request
        pending_request = AccessRequest.objects.filter(
            team=team, user=user, status=AccessRequest.Status.PENDING
        ).first()
        if pending_request:
            # Check if NDA is required and not signed yet
            if requires_nda:
                has_signed = NDASignature.objects.live().filter(access_request=pending_request).exists()
                if not has_signed:
                    # Request exists but NDA not signed - redirect to sign NDA page
                    return redirect("documents:sign_nda", team_key=team_key, request_id=pending_request.id)
            # Request is complete (either no NDA required or NDA already signed)
            messages.info(request, "Your access request is already pending approval.")
            return redirect("core:workspace_public", workspace_key=team_key)

        # A revoked or rejected request is reopened rather than duplicated
        with transaction.atomic():
            access_request, request_state_changed = request_access(team, user)

        # Invalidate cache after transaction commits to avoid long-running transaction
        transaction.on_commit(lambda: invalidate_access_requests_cache(team))

        # AccessRequest is workspace-scoped (no component_id field). Issue #817 listed
        # `component_id` as a property but the access-request flow is per-workspace.
        # Only fire on a state transition (new request or revoked/rejected → pending
        # re-request) so duplicate submissions for an already-pending or approved
        # request do not inflate the funnel.
        # Deferred via ``on_commit`` to mirror the cache-invalidate above so the
        # event only ships if the create/update transaction committed.
        if request_state_changed:
            transaction.on_commit(
                lambda: capture_for_request(
                    request,
                    "document:access_requested",
                    {"requires_nda": requires_nda},
                    team_key=team_key,
                )
            )

        # Only send notification if NDA is not required (request is complete)
        # If NDA is required, notification will be sent after NDA is signed
        if not requires_nda:
            notify_admins_of_access_request(access_request, team, requires_nda=False)
            messages.success(request, "Access request submitted. You will be notified when it's approved.")
            return redirect("core:workspace_public", workspace_key=team_key)

        # NDA is required - redirect to signing page
        # Request will remain pending until NDA is signed
        return redirect("documents:sign_nda", team_key=team_key, request_id=access_request.id)


@method_decorator(never_cache, name="dispatch")
class NDASigningView(View):
    """View for signing NDA as part of access request."""

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        # Only the requester reads and signs their NDA, so they sign in first.
        if not request.user.is_authenticated:
            return redirect(f"{reverse('core:keycloak_login')}?next={quote(request.get_full_path())}")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, team_key: str, request_id: str) -> HttpResponse:
        """Show NDA document for signing."""
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            return error_response(request, HttpResponse(status=404, content="Team not found"))

        try:
            access_request = AccessRequest.objects.select_related("user", "team").get(id=request_id, team=team)
        except AccessRequest.DoesNotExist:
            return error_response(request, HttpResponse(status=404, content="Access request not found"))

        # Verify user owns the request
        if access_request.user != request.user:
            return error_response(request, HttpResponse(status=403, content="Forbidden"))

        # Get company-wide NDA
        company_nda = team.get_company_nda_document()
        if not company_nda:
            return error_response(request, HttpResponse(status=404, content="NDA document not found"))

        # Check if already signed for the current NDA document
        existing_signature = (
            NDASignature.objects.live().filter(access_request=access_request, nda_document=company_nda).first()
        )
        if existing_signature:
            messages.info(request, "NDA has already been signed for this request.")
            # Redirect to return URL if available, otherwise to workspace public page
            return_url = request.session.get("nda_signing_return_url")
            if return_url:
                return redirect(return_url)
            return redirect("core:workspace_public", workspace_key=team_key)

        # Build branding context for the template
        brand = build_branding_context(team)

        return render(
            request,
            "documents/sign_nda.html.j2",
            {
                "team": team,
                "brand": brand,
                "access_request": access_request,
                "nda_document": company_nda,
            },
        )

    def post(self, request: HttpRequest, team_key: str, request_id: str) -> HttpResponse:
        """Process NDA signature."""
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            return error_response(request, HttpResponse(status=404, content="Team not found"))

        try:
            access_request = AccessRequest.objects.select_related("user", "team").get(id=request_id, team=team)
        except AccessRequest.DoesNotExist:
            return error_response(request, HttpResponse(status=404, content="Access request not found"))

        # Verify user owns the request
        if access_request.user != request.user:
            return error_response(request, HttpResponse(status=403, content="Forbidden"))

        # Get company-wide NDA
        company_nda = team.get_company_nda_document()
        if not company_nda:
            return error_response(request, HttpResponse(status=404, content="NDA document not found"))

        # Check if already signed for the current NDA document
        existing_signature = (
            NDASignature.objects.live().filter(access_request=access_request, nda_document=company_nda).first()
        )
        if existing_signature:
            messages.info(request, "NDA has already been signed for this request.")
            # Redirect to return URL if available, otherwise to workspace public page
            return_url = request.session.get("nda_signing_return_url")
            if return_url:
                return redirect(return_url)
            return redirect("core:workspace_public", workspace_key=team_key)

        # Get form data
        signed_name = request.POST.get("signed_name", "").strip()
        consent = request.POST.get("consent") == "on"

        if not signed_name:
            messages.error(request, "Name is required")
            return redirect("documents:sign_nda", team_key=team_key, request_id=request_id)

        if not consent:
            messages.error(request, "You must consent to the NDA terms")
            return redirect("documents:sign_nda", team_key=team_key, request_id=request_id)

        try:
            # Get NDA document content and calculate hash
            s3 = StorageClient("DOCUMENTS")
            document_data = s3.get_document_data(company_nda.document_filename)
            if not document_data:
                messages.error(request, "NDA document not found in storage")
                return redirect("documents:sign_nda", team_key=team_key, request_id=request_id)
            nda_content_hash = hashlib.sha256(document_data).hexdigest()

            # Verify document hasn't been modified (compare with stored content_hash)
            if company_nda.content_hash and nda_content_hash != company_nda.content_hash:
                messages.error(
                    request, "The NDA document has been modified. Please contact the workspace administrator."
                )
                logger.warning(
                    f"NDA document {company_nda.id} content hash mismatch during signing. "
                    f"Expected: {company_nda.content_hash}, Got: {nda_content_hash}"
                )
                return redirect("documents:sign_nda", team_key=team_key, request_id=request_id)

            # Wrap NDA signing and related operations in a transaction
            with transaction.atomic():
                _, access_request = record_nda_signature(
                    request, access_request, company_nda, nda_content_hash, signed_name
                )

                # Inside the atomic block so transaction.on_commit deferral applies.
                transaction.on_commit(lambda: capture_for_request(request, "nda:signed", team_key=team_key))

            # Check if there's a pending invitation for this user (from trust center invite)
            pending_invitation_token = request.session.pop("pending_invitation_token", None)
            if pending_invitation_token:
                current_user = cast(User, request.user)
                invitation = Invitation.objects.filter(token=pending_invitation_token, team=team).first()
                if invitation and invitation_email(current_user).lower() == invitation.email.lower():
                    # Get inviter from cache if available
                    cache_key = f"invitation_inviter:{invitation.token}"
                    inviter_id = cache.get(cache_key)
                    if inviter_id:
                        cache.delete(cache_key)  # Clean up after use

                    # Check if user is already a member
                    if not Member.objects.filter(team=team, user=current_user).exists():
                        # Complete invitation acceptance
                        # Counted and taken under one lock, so an NDA signed at the same
                        # moment as another acceptance cannot take the same last seat twice.
                        with user_seat(team, is_joining_via_invite=True) as (can_add, error_message):
                            if can_add:
                                has_default_team = Member.objects.filter(
                                    user=current_user, is_default_team=True
                                ).exists()
                                joined_role = invitation.granted_role
                                Member.objects.create(
                                    team=team,
                                    user=current_user,
                                    role=joined_role,
                                    is_default_team=not has_default_team,
                                )
                                update_user_teams_session(request, current_user)
                                switch_active_workspace(request, team, joined_role)

                                # NDA-gated invitations bypass both accept_invite and the
                                # login auto-accept signal; without this capture the
                                # collaboration funnel undercounts invited users who had
                                # to sign an NDA before joining.
                                invitation_role = joined_role
                                transaction.on_commit(
                                    lambda: capture_for_request(
                                        request,
                                        "team:member_invitation_accepted",
                                        {"role": invitation_role},
                                        team_key=team_key,
                                    )
                                )

                                invitation.delete()

                                # Auto-approve the access request since user has been invited and is now a member
                                was_pending = access_request.status == AccessRequest.Status.PENDING
                                access_request.status = AccessRequest.Status.APPROVED
                                access_request.decided_at = timezone.now()
                                # Set decided_by to the inviter if available, otherwise leave as None
                                if inviter_id:
                                    try:
                                        inviter = get_user_model().objects.get(id=inviter_id)
                                        access_request.decided_by = inviter
                                    except get_user_model().DoesNotExist:
                                        # Inviter user not found, continue without setting decided_by
                                        pass
                                access_request.save()

                                # Only emit document:access_approved when this is genuinely a
                                # trust-center invitation (signalled by the `invitation_inviter:`
                                # cache key set in documents/views/access_requests.py at invite
                                # send time). Regular workspace invites with a company NDA also
                                # reach this branch and approve a freshly-created plumbing
                                # AccessRequest; counting them would inflate the funnel.
                                if was_pending and inviter_id:
                                    transaction.on_commit(
                                        lambda: capture_for_request(
                                            request, "document:access_approved", team_key=team_key
                                        )
                                    )

                                # Invalidate cache after transaction commits
                                transaction.on_commit(lambda: invalidate_access_requests_cache(team))

                                messages.success(
                                    request,
                                    f"NDA signed successfully. You have joined {team.name} as {invitation.role}.",
                                )

                                # Check for return URL in session
                                return_url = request.session.pop("nda_signing_return_url", None)
                                if return_url:
                                    return redirect(return_url)

                                return redirect("core:dashboard")
                            else:
                                messages.error(request, error_message)
                                return redirect("core:workspace_public", workspace_key=team_key)
                    else:
                        # User is already a member, just complete the invitation
                        # But still approve the access request if it's pending
                        invitation.delete()

                        # Get inviter from cache if available
                        cache_key = f"invitation_inviter:{invitation.token}"
                        inviter_id = cache.get(cache_key)
                        if inviter_id:
                            cache.delete(cache_key)  # Clean up after use

                        # Auto-approve the access request if it's still pending
                        if access_request.status == AccessRequest.Status.PENDING:
                            access_request.status = AccessRequest.Status.APPROVED
                            access_request.decided_at = timezone.now()
                            # Set decided_by to the inviter if available, otherwise leave as None
                            if inviter_id:
                                try:
                                    inviter = get_user_model().objects.get(id=inviter_id)
                                    access_request.decided_by = inviter
                                except get_user_model().DoesNotExist:
                                    # Inviter user not found, continue without setting decided_by
                                    pass
                            access_request.save()

                            # Invalidate cache after transaction commits
                            transaction.on_commit(lambda: invalidate_access_requests_cache(team))

                        messages.success(request, "NDA signed successfully.")

                        # Check for return URL in session
                        return_url = request.session.pop("nda_signing_return_url", None)
                        if return_url:
                            return redirect(return_url)

                        return redirect("core:dashboard")

            # Only a pending request is waiting on the admins; a re-signed or closed one is not news to them
            if access_request.status == AccessRequest.Status.PENDING:
                transaction.on_commit(lambda: invalidate_access_requests_cache(team))
                transaction.on_commit(lambda: notify_admins_of_access_request(access_request, team, requires_nda=True))
                messages.success(
                    request,
                    "NDA signed successfully. Your access request has been submitted and is pending approval.",
                )
            else:
                messages.success(request, "NDA signed successfully.")

            # Check for return URL in session
            return_url = request.session.pop("nda_signing_return_url", None)
            if return_url:
                return redirect(return_url)

            return redirect("core:workspace_public", workspace_key=team_key)

        except Exception as e:
            logger.error(f"Error signing NDA: {e}")
            messages.error(request, "Failed to sign NDA. Please try again.")
            return redirect("documents:sign_nda", team_key=team_key, request_id=request_id)


@method_decorator(never_cache, name="dispatch")
class AccessRequestQueueView(TeamRoleRequiredMixin, LoginRequiredMixin, View):
    """Admin view to approve/reject/revoke access requests."""

    allowed_roles = list(ADMINISTER)

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        """List pending access requests.

        The template below is a section, not a page: it extends no base, so a
        browser sent straight here got the markup with no stylesheet, no script
        and nothing that works. The notification email pointed its "Review
        request" button at this URL, so every admin reviewing a request landed
        on that. Its real home is the trust-center tab of workspace settings,
        which renders this same section inside the page, and a direct visit goes
        there. htmx keeps getting the section, which is what the tab swaps.
        """
        user = cast(User, request.user)
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            return error_response(request, HttpResponse(status=404, content="Team not found"))

        if request.headers.get("HX-Request") != "true":
            return redirect("teams:team_settings_tab", team_key=team.key, tab="trust-center")

        # Verify user is owner or admin
        try:
            member = Member.objects.get(team=team, user=user)
            if member.role not in ADMINISTER:
                return error_response(request, HttpResponse(status=403, content="Access denied"))
        except Member.DoesNotExist:
            return error_response(request, HttpResponse(status=403, content="Access denied"))

        return _queue_response(request, team)

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:  # noqa: C901
        """Approve, reject, or revoke access request."""
        user = cast(User, request.user)
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            return error_response(request, HttpResponse(status=404, content="Team not found"))

        # Verify user is owner or admin
        try:
            member = Member.objects.get(team=team, user=user)
            if member.role not in ADMINISTER:
                return error_response(request, HttpResponse(status=403, content="Access denied"))
        except Member.DoesNotExist:
            return error_response(request, HttpResponse(status=403, content="Access denied"))

        action = request.POST.get("action")
        request_id = request.POST.get("request_id")
        active_tab = request.POST.get("active_tab", "")

        # Handle cancel invitation action
        if action == "cancel_invitation":
            invitation_id = request.POST.get("invitation_id")
            if not invitation_id:
                messages.error(request, "Invalid invitation ID")
                return _back(team_key, active_tab)

            try:
                invitation = Invitation.objects.get(id=invitation_id, team=team)
                email = invitation.email
                invitation.delete()

                # Also clean up cache entry if it exists
                cache_key = f"invitation_inviter:{invitation.token}"
                cache.delete(cache_key)

                messages.success(request, f"Invitation to {email} has been cancelled")

                # For HTMX requests, return the updated access request queue
                if request.headers.get("HX-Request") == "true":
                    return _queue_response(request, team)

                return _back(team_key, active_tab)

            except Invitation.DoesNotExist:
                messages.error(request, "Invitation not found")
                return _back(team_key, active_tab)

        # Handle invite action (doesn't require request_id)
        if action == "invite":
            email = request.POST.get("email", "").strip()
            if not email:
                messages.error(request, "Email is required")
                return _back(team_key, active_tab)

            # Check if user is already a member
            UserModel = get_user_model()
            try:
                invitee = UserModel.objects.get(email__iexact=email)
                if Member.objects.filter(team=team, user=invitee).exists():
                    messages.error(request, f"{email} is already a member of this workspace")
                    return _back(team_key, active_tab)
            except (UserModel.DoesNotExist, UserModel.MultipleObjectsReturned):
                # User doesn't exist yet, will be created when they accept invitation
                pass

            # Check if invitation already exists (non-expired)
            existing_invitation = Invitation.objects.filter(email__iexact=email, team=team).first()
            if existing_invitation:
                if existing_invitation.has_expired:
                    existing_invitation.delete()
                else:
                    messages.error(request, f"Invitation already sent to {email}")
                    return _back(team_key, active_tab)

            # Create invitation
            invitation = Invitation.objects.create(team=team, email=email, role="guest")

            # Store inviter info in cache for later use when auto-approving access request
            # This allows us to set decided_by to the person who sent the invitation
            cache_key = f"invitation_inviter:{invitation.token}"
            cache.set(cache_key, user.id, timeout=60 * 60 * 24 * 7)  # 7 days (same as invitation expiry)

            # If user already exists, create/update AccessRequest with inviter set as decided_by.
            # Only an account that confirmed the address counts as its holder.
            try:
                invited_user = UserModel.objects.get(email__iexact=email, email_verified=True)
                access_request, created = AccessRequest.objects.get_or_create(
                    team=team,
                    user=invited_user,
                    defaults={
                        "status": AccessRequest.Status.PENDING,
                        "decided_by": user,  # Set inviter as decided_by
                    },
                )
                # If AccessRequest already exists, update decided_by if not set
                if not created and not access_request.decided_by:
                    access_request.decided_by = user
                    access_request.save(update_fields=["decided_by"])
            except (UserModel.DoesNotExist, UserModel.MultipleObjectsReturned):
                # User doesn't exist yet, will be handled when they accept invitation
                pass

            # Send invitation email

            email_context = {
                "team": team,
                "invitation": invitation,
                "user": user,
                "base_url": get_base_url(),
            }
            trust_email = EmailMultiAlternatives(
                subject=f"You're invited to the {team.name} Trust Center",
                body=render_to_string("teams/emails/trust_center_invite_email.txt", email_context),
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email],
                reply_to=["hello@sbomify.com"],
            )
            trust_email.attach_alternative(
                render_to_string("teams/emails/trust_center_invite_email.html.j2", email_context), "text/html"
            )
            trust_email.send()

            messages.success(request, f"Invitation sent to {email}")

            # For HTMX requests, return the updated access request queue
            if request.headers.get("HX-Request") == "true":
                return _queue_response(request, team, "closeInviteModal")

            return _back(team_key, active_tab)

        if not action or not request_id:
            messages.error(request, "Invalid request")
            return _back(team_key, active_tab)

        with transaction.atomic():
            # Lock the access request row to prevent race conditions
            try:
                access_request = (
                    AccessRequest.objects.select_for_update()
                    .select_related("user", "team")
                    .get(id=request_id, team=team)
                )
            except AccessRequest.DoesNotExist:
                messages.error(request, "Access request not found")
                return _back(team_key, active_tab)

            if action == "approve":
                # Check status inside transaction after locking
                if access_request.status != AccessRequest.Status.PENDING:
                    messages.error(request, "Access request is not pending")
                    return _back(team_key, active_tab)

                approve_request(access_request, user)

            elif action == "reject":
                # Check status inside transaction after locking
                if access_request.status != AccessRequest.Status.PENDING:
                    messages.error(request, "Access request is not pending")
                    return _back(team_key, active_tab)

                reject_request(access_request, user)

            elif action == "revoke":
                # Check status inside transaction after locking
                if access_request.status != AccessRequest.Status.APPROVED:
                    messages.error(request, "Access request is not approved")
                    return _back(team_key, active_tab)

                revoke_request(access_request, user)

            elif action == "clear_rejection":
                # Check status inside transaction after locking
                if access_request.status != AccessRequest.Status.REJECTED:
                    messages.error(request, "Access request is not rejected")
                    return _back(team_key, active_tab)

                # Store user email before deleting
                user_email = access_request.user.email

                # Delete the access request so user can re-request
                access_request.delete()

                # Set flag to skip post-transaction actions that reference access_request
                action = "clear_rejection_done"

                messages.success(request, f"Removed {user_email} from rejected list.")

            else:
                messages.error(request, "Invalid action")
                return _back(team_key, active_tab)

        # Invalidate cache after transaction commits
        transaction.on_commit(lambda: invalidate_access_requests_cache(team))

        # Handle post-transaction actions based on action type
        if action == "approve":
            # Invalidate the approved user's session cache so workspace appears immediately
            cache_key = f"user_teams_invalidate:{access_request.user.id}"
            cache.set(cache_key, True, timeout=600)  # 10 minutes should be enough

            # Mirror the cache-invalidate above: defer via ``on_commit`` so
            # the event only ships if the approval transaction commits. In
            # autocommit mode (current prod) this fires immediately; if the
            # view ever runs under ``ATOMIC_REQUESTS`` it stays correct.
            transaction.on_commit(lambda: capture_for_request(request, "document:access_approved", team_key=team_key))

            notify_access_approved(access_request)

            messages.success(
                request,
                f"Access request approved. {access_request.user.email} now has access to "
                f"gated components as a guest member.",
            )

        elif action == "reject":
            # Mirror the approve branch above: defer via ``on_commit`` so the
            # event only ships if the reject transaction committed.
            transaction.on_commit(lambda: capture_for_request(request, "document:access_denied", team_key=team_key))

            notify_access_rejected(access_request)

            messages.success(request, "Access request rejected.")

        elif action == "revoke":
            # Invalidate the revoked user's session cache so workspace disappears immediately
            cache_key = f"user_teams_invalidate:{access_request.user.id}"
            cache.set(cache_key, True, timeout=600)  # 10 minutes should be enough

            notify_access_revoked(access_request)

            messages.success(request, f"Access revoked for {access_request.user.email}.")

        # Dismiss notification if no more pending requests
        dismiss_access_request_notification_if_no_pending(request, team)

        # For HTMX requests, return the updated access request queue content
        if request.headers.get("HX-Request") == "true":
            return _queue_response(request, team)

        return _back(team_key, active_tab)
