import hashlib
import logging
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache

from sbomify.apps.core.errors import error_response
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.teams.models import Invitation, Member, Team
from sbomify.apps.teams.permissions import TeamRoleRequiredMixin
from sbomify.apps.teams.utils import (
    can_add_user_to_team,
    switch_active_workspace,
    update_user_teams_session,
)

logger = logging.getLogger(__name__)


def user_has_signed_current_nda(user, team):
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

    return _user_has_signed_current_nda(user, team)


def _invalidate_access_requests_cache(team: Team):
    """Invalidate cache for pending access requests count for all owners/admins of the team."""
    admin_members = Member.objects.filter(team=team, role__in=("owner", "admin")).values_list("user_id", flat=True)

    for user_id in admin_members:
        cache_key = f"pending_access_requests:{team.key}:{user_id}"
        cache.delete(cache_key)


def _get_pending_access_requests(team: Team):
    """Get pending access requests for a team, filtering by NDA signature if required.

    Args:
        team: Team instance to get requests for

    Returns:
        QuerySet of pending AccessRequest objects with optimized prefetching
    """
    company_nda = team.get_company_nda_document()
    requires_nda = company_nda is not None

    base_queryset = (
        AccessRequest.objects.filter(team=team, status=AccessRequest.Status.PENDING)
        .select_related("user", "decided_by")
        .prefetch_related("nda_signature__nda_document")
        .order_by("-requested_at")
    )

    if requires_nda:
        # Only show requests that have NDA signature (request is complete)
        signed_request_ids = NDASignature.objects.values_list("access_request_id", flat=True)
        return base_queryset.filter(id__in=signed_request_ids)

    return base_queryset


def _get_approved_access_requests(team: Team):
    """Get approved access requests for a team.

    Args:
        team: Team instance to get requests for

    Returns:
        QuerySet of approved AccessRequest objects with optimized prefetching
    """
    return (
        AccessRequest.objects.filter(team=team, status=AccessRequest.Status.APPROVED)
        .select_related("user", "decided_by")
        .prefetch_related("nda_signature__nda_document")
        .order_by("-decided_at")
    )


def _annotate_nda_signature_status(requests, company_nda):
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
        current_signatures = {
            sig.access_request_id
            for sig in NDASignature.objects.filter(
                access_request_id__in=request_ids, nda_document=company_nda
            ).values_list("access_request_id", flat=True)
        }
        for req in requests:
            req.has_current_nda_signature = req.id in current_signatures
    else:
        # No NDA required, so signature status doesn't matter
        for req in requests:
            req.has_current_nda_signature = True


def _dismiss_access_request_notification_if_no_pending(request: HttpRequest, team: Team):
    """Dismiss the access request notification if there are no more pending requests."""
    # Check if there are any pending requests left
    pending_requests = _get_pending_access_requests(team)
    pending_count = pending_requests.count()

    # If no pending requests, dismiss the notification
    if pending_count == 0:
        notification_id = f"access_request_pending_{team.key}"
        dismissed_ids = set(request.session.get("dismissed_notifications", []))
        dismissed_ids.add(notification_id)
        request.session["dismissed_notifications"] = list(dismissed_ids)
        request.session.save()


def _notify_admins_of_access_request(access_request: AccessRequest, team: Team, requires_nda: bool = False):
    """Send email notification to all owners and admins about a new access request."""
    try:
        # Get all owners and admins of the team
        admin_members = Member.objects.filter(team=team, role__in=("owner", "admin")).select_related("user")

        if not admin_members.exists():
            logger.warning(f"No admins found for team {team.key} to notify about access request {access_request.id}")
            return

        # Build email context
        requester_name = (
            f"{access_request.user.first_name} {access_request.user.last_name}".strip() or access_request.user.username
        )
        requester_email = access_request.user.email
        review_url = reverse("documents:access_request_queue", kwargs={"team_key": team.key})
        review_link = f"{settings.APP_BASE_URL}{review_url}"

        # Check if NDA has actually been signed
        nda_signed = NDASignature.objects.filter(access_request=access_request).exists()

        # Send email to each admin/owner
        for admin_member in admin_members:
            try:
                email_context = {
                    "admin_user": admin_member.user,
                    "team": team,
                    "requester_name": requester_name,
                    "requester_email": requester_email,
                    "requested_at": access_request.requested_at.strftime("%B %d, %Y at %I:%M %p"),
                    "requires_nda": requires_nda,
                    "nda_signed": nda_signed,
                    "review_link": review_link,
                    "base_url": settings.APP_BASE_URL,
                }

                send_mail(
                    subject=f"New Access Request - {team.name}",
                    message=render_to_string("documents/emails/access_request_notification.txt", email_context),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[admin_member.user.email],
                    html_message=render_to_string(
                        "documents/emails/access_request_notification.html.j2", email_context
                    ),
                )
            except Exception as e:
                logger.error(f"Failed to send access request notification to {admin_member.user.email}: {e}")

    except Exception as e:
        logger.error(f"Error notifying admins of access request {access_request.id}: {e}")


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
                if member.role in ("owner", "admin", "guest"):
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

        # Always check for company-wide NDA - if it exists, always require signing
        company_nda = team.get_company_nda_document()
        requires_nda = company_nda is not None

        return render(
            request,
            "documents/request_access.html.j2",
            {
                "team": team,
                "company_nda": company_nda,
                "requires_nda": requires_nda,
                "user": request.user if request.user.is_authenticated else None,
            },
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        """Create access request."""
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            return error_response(request, HttpResponse(status=404, content="Team not found"))

        # Get or create user
        User = get_user_model()
        user = None

        if request.user.is_authenticated:
            user = request.user
        else:
            email = request.POST.get("email")
            if not email:
                messages.error(request, "Email is required")
                return redirect("documents:request_access", team_key=team_key)

            name = request.POST.get("name", "")

            # Check if user already exists
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                # Create new user
                username = email.split("@")[0]
                base_username = username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}_{counter}"
                    counter += 1

                user = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=name or "",
                )

        # Check if user already has access
        try:
            member = Member.objects.get(team=team, user=user)
            if member.role in ("owner", "admin", "guest"):
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
                has_signed = NDASignature.objects.filter(access_request=pending_request).exists()
                if not has_signed:
                    # Request exists but NDA not signed - redirect to sign NDA page
                    return redirect("documents:sign_nda", team_key=team_key, request_id=pending_request.id)
            # Request is complete (either no NDA required or NDA already signed)
            messages.info(request, "Your access request is already pending approval.")
            return redirect("core:workspace_public", workspace_key=team_key)

        # Check for existing request (REVOKED or REJECTED) - if exists, update it to PENDING instead of creating new one
        with transaction.atomic():
            # Use select_for_update to prevent race conditions
            existing_request = AccessRequest.objects.select_for_update().filter(team=team, user=user).first()

            # Create or update access request
            access_request = None
            if existing_request:
                # If request is REVOKED or REJECTED, update it to PENDING
                if existing_request.status in (AccessRequest.Status.REVOKED, AccessRequest.Status.REJECTED):
                    # Note: Old NDA signature remains linked to the old document version.
                    # It will be replaced (not archived) when user signs the current NDA version
                    # due to OneToOneField constraint. For full audit history, consider
                    # changing the model to allow multiple signatures per access_request.

                    # Update existing request to PENDING status
                    existing_request.status = AccessRequest.Status.PENDING
                    existing_request.requested_at = timezone.now()
                    existing_request.decided_at = None
                    existing_request.decided_by = None
                    existing_request.revoked_at = None
                    existing_request.revoked_by = None
                    existing_request.notes = ""
                    existing_request.save()
                    access_request = existing_request
                elif existing_request.status == AccessRequest.Status.PENDING:
                    # Request already exists and is pending
                    access_request = existing_request
                else:
                    # Request is APPROVED - user already has access
                    access_request = existing_request
            else:
                # Create new access request using get_or_create to handle race conditions
                try:
                    access_request, created = AccessRequest.objects.get_or_create(
                        team=team,
                        user=user,
                        defaults={"status": AccessRequest.Status.PENDING},
                    )
                    if not created:
                        # Another request was created concurrently, refresh from DB
                        access_request.refresh_from_db()
                except IntegrityError:
                    # Race condition: another request was created between check and create
                    # Fetch the existing request
                    try:
                        access_request = AccessRequest.objects.get(team=team, user=user)
                    except AccessRequest.DoesNotExist:
                        # Extremely rare: row was deleted between IntegrityError and get()
                        # Retry get_or_create one more time
                        access_request, _ = AccessRequest.objects.get_or_create(
                            team=team, user=user, defaults={"status": AccessRequest.Status.PENDING}
                        )

        # Invalidate cache after transaction commits to avoid long-running transaction
        transaction.on_commit(lambda: _invalidate_access_requests_cache(team))

        # Only send notification if NDA is not required (request is complete)
        # If NDA is required, notification will be sent after NDA is signed
        if not requires_nda:
            _notify_admins_of_access_request(access_request, team, requires_nda=False)
            messages.success(request, "Access request submitted. You will be notified when it's approved.")
            return redirect("core:workspace_public", workspace_key=team_key)

        # NDA is required - redirect to signing page
        # Request will remain pending until NDA is signed
        return redirect("documents:sign_nda", team_key=team_key, request_id=access_request.id)


@method_decorator(never_cache, name="dispatch")
class NDASigningView(View):
    """View for signing NDA as part of access request."""

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
        if request.user.is_authenticated:
            if access_request.user != request.user:
                return error_response(request, HttpResponse(status=403, content="Forbidden"))
        else:
            # For unauthenticated, verify request is pending
            if access_request.status != AccessRequest.Status.PENDING:
                return error_response(request, HttpResponse(status=403, content="Forbidden"))

        # Get company-wide NDA
        company_nda = team.get_company_nda_document()
        if not company_nda:
            # For unauthenticated users, return 403 instead of 404 to avoid information disclosure
            if not request.user.is_authenticated:
                return error_response(request, HttpResponse(status=403, content="Forbidden"))
            return error_response(request, HttpResponse(status=404, content="NDA document not found"))

        # Check if already signed for the current NDA document
        existing_signature = NDASignature.objects.filter(
            access_request=access_request, nda_document=company_nda
        ).first()
        if existing_signature:
            messages.info(request, "NDA has already been signed for this request.")
            # Redirect to return URL if available, otherwise to workspace public page
            return_url = request.session.get("nda_signing_return_url")
            if return_url:
                return redirect(return_url)
            return redirect("core:workspace_public", workspace_key=team_key)

        return render(
            request,
            "documents/sign_nda.html.j2",
            {
                "team": team,
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
        if request.user.is_authenticated:
            if access_request.user != request.user:
                return error_response(request, HttpResponse(status=403, content="Forbidden"))
        else:
            # For unauthenticated, verify request is pending
            if access_request.status != AccessRequest.Status.PENDING:
                return error_response(request, HttpResponse(status=403, content="Forbidden"))

        # Get company-wide NDA
        company_nda = team.get_company_nda_document()
        if not company_nda:
            # For unauthenticated users, return 403 instead of 404 to avoid information disclosure
            if not request.user.is_authenticated:
                return error_response(request, HttpResponse(status=403, content="Forbidden"))
            return error_response(request, HttpResponse(status=404, content="NDA document not found"))

        # Check if already signed for the current NDA document
        existing_signature = NDASignature.objects.filter(
            access_request=access_request, nda_document=company_nda
        ).first()
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
            s3 = S3Client("DOCUMENTS")
            document_data = s3.get_document_data(company_nda.document_filename)
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
                # Check if there's an existing signature for a different NDA document
                # (e.g., user signed old version, now signing new version)
                # Since OneToOneField only allows one signature per access_request,
                # we need to delete the old one before creating the new one
                # NOTE: This loses audit history. For full audit trail, consider changing
                # the model to allow multiple signatures per access_request.
                if hasattr(access_request, "nda_signature"):
                    old_signature = access_request.nda_signature
                    if old_signature.nda_document != company_nda:
                        logger.info(
                            f"Replacing old NDA signature {old_signature.id} "
                            f"for document {old_signature.nda_document.id} "
                            f"with new signature for document {company_nda.id}"
                        )
                        old_signature.delete()

                # Create NDA signature
                NDASignature.objects.create(
                    access_request=access_request,
                    nda_document=company_nda,
                    nda_content_hash=nda_content_hash,
                    signed_name=signed_name,
                    ip_address=request.META.get("REMOTE_ADDR"),
                    user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
                )

                # Reload access request with NDA signature relationship
                access_request = AccessRequest.objects.prefetch_related("nda_signature").get(pk=access_request.id)

            # Check if there's a pending invitation for this user (from trust center invite)
            pending_invitation_token = request.session.pop("pending_invitation_token", None)
            if pending_invitation_token:
                invitation = Invitation.objects.filter(token=pending_invitation_token, team=team).first()
                if invitation and (request.user.email or "").lower() == invitation.email.lower():
                    # Get inviter from cache if available
                    cache_key = f"invitation_inviter:{invitation.token}"
                    inviter_id = cache.get(cache_key)
                    if inviter_id:
                        cache.delete(cache_key)  # Clean up after use

                    # Check if user is already a member
                    if not Member.objects.filter(team=team, user=request.user).exists():
                        # Complete invitation acceptance
                        can_add, error_message = can_add_user_to_team(team, is_joining_via_invite=True)
                        if can_add:
                            has_default_team = Member.objects.filter(user=request.user, is_default_team=True).exists()
                            Member.objects.create(
                                team=team,
                                user=request.user,
                                role=invitation.role,
                                is_default_team=not has_default_team,
                            )
                            update_user_teams_session(request, request.user)
                            switch_active_workspace(request, team, invitation.role)

                            invitation.delete()

                            # Auto-approve the access request since user has been invited and is now a member
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
                            transaction.on_commit(lambda: _invalidate_access_requests_cache(team))

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
                            transaction.on_commit(lambda: _invalidate_access_requests_cache(team))

                        messages.success(request, "NDA signed successfully.")

                        # Check for return URL in session
                        return_url = request.session.pop("nda_signing_return_url", None)
                        if return_url:
                            return redirect(return_url)

                        return redirect("core:dashboard")

            # Now that NDA is signed, send notification to admins (request is now complete)
            # Invalidate cache after transaction commits
            transaction.on_commit(lambda: _invalidate_access_requests_cache(team))
            transaction.on_commit(lambda: _notify_admins_of_access_request(access_request, team, requires_nda=True))

            messages.success(
                request, "NDA signed successfully. Your access request has been submitted and is pending approval."
            )

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

    allowed_roles = ["owner", "admin"]

    def get(self, request: HttpRequest, team_key: str) -> HttpResponse:
        """List pending access requests."""
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            return error_response(request, HttpResponse(status=404, content="Team not found"))

        # Verify user is owner or admin
        try:
            member = Member.objects.get(team=team, user=request.user)
            if member.role not in ("owner", "admin"):
                return error_response(request, HttpResponse(status=403, content="Access denied"))
        except Member.DoesNotExist:
            return error_response(request, HttpResponse(status=403, content="Access denied"))

        # Get pending and approved requests using helper functions
        company_nda = team.get_company_nda_document()
        pending_requests = list(_get_pending_access_requests(team))
        approved_requests = list(_get_approved_access_requests(team))

        # Annotate requests with current NDA signature status
        _annotate_nda_signature_status(pending_requests, company_nda)
        _annotate_nda_signature_status(approved_requests, company_nda)

        # Get pending invitations (invited but not yet accepted)
        User = get_user_model()
        pending_invitations = Invitation.objects.filter(team=team).order_by("-created_at")

        # Try to get inviter info from cache for each invitation
        # Fallback: check AccessRequest if user already exists
        invitations_with_inviter = []
        for invitation in pending_invitations:
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
                except User.DoesNotExist:
                    # Invited user not found, continue without inviter_email
                    pass

            invitations_with_inviter.append(
                {
                    "invitation": invitation,
                    "inviter_email": inviter_email,
                }
            )

        # Check if this is a partial request (for embedding in trust center tab)
        # is_partial = request.headers.get("HX-Request") == "true" or request.GET.get("partial") == "true"

        # Use content template for partial requests, otherwise use the content template wrapped in a page
        # The full page template doesn't exist - it's embedded in team settings
        template_name = "documents/access_request_queue_content.html.j2"

        return render(
            request,
            template_name,
            {
                "team": team,
                "pending_requests": pending_requests,
                "approved_requests": approved_requests,
                "pending_invitations": invitations_with_inviter,
            },
        )

    def post(self, request: HttpRequest, team_key: str) -> HttpResponse:
        """Approve, reject, or revoke access request."""
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            return error_response(request, HttpResponse(status=404, content="Team not found"))

        # Verify user is owner or admin
        try:
            member = Member.objects.get(team=team, user=request.user)
            if member.role not in ("owner", "admin"):
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
                if active_tab == "trust-center":
                    response = redirect(
                        reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}"
                    )
                    response["HX-Trigger"] = "refreshAccessRequests"
                    return response
                return redirect("documents:access_request_queue", team_key=team_key)

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
                    # Get updated requests using helper functions
                    company_nda = team.get_company_nda_document()
                    pending_requests = list(_get_pending_access_requests(team))
                    approved_requests = list(_get_approved_access_requests(team))
                    _annotate_nda_signature_status(pending_requests, company_nda)
                    _annotate_nda_signature_status(approved_requests, company_nda)

                    # Get pending invitations
                    pending_invitations_list = Invitation.objects.filter(team=team).order_by("-created_at")

                    # Try to get inviter info from cache for each invitation
                    # Fallback: check AccessRequest if user already exists
                    invitations_with_inviter = []
                    for inv in pending_invitations_list:
                        inviter_email = None
                        cache_key_inv = f"invitation_inviter:{inv.token}"
                        inviter_id = cache.get(cache_key_inv)
                        if inviter_id:
                            User = get_user_model()
                            try:
                                inviter = User.objects.get(id=inviter_id)
                                inviter_email = inviter.email
                            except User.DoesNotExist:
                                # Inviter user not found in cache, continue without inviter_email
                                pass

                        # Fallback: check if user exists and has an AccessRequest with decided_by set
                        if not inviter_email:
                            try:
                                invited_user = User.objects.get(email__iexact=inv.email)
                                access_request = AccessRequest.objects.filter(
                                    team=team, user=invited_user, decided_by__isnull=False
                                ).first()
                                if access_request and access_request.decided_by:
                                    inviter_email = access_request.decided_by.email
                            except User.DoesNotExist:
                                # Invited user not found, continue without inviter_email
                                pass

                        invitations_with_inviter.append(
                            {
                                "invitation": inv,
                                "inviter_email": inviter_email,
                            }
                        )

                    html = render_to_string(
                        "documents/access_request_queue_content.html.j2",
                        {
                            "team": team,
                            "pending_requests": pending_requests,
                            "approved_requests": approved_requests,
                            "pending_invitations": invitations_with_inviter,
                        },
                        request=request,
                    )
                    response = HttpResponse(html)
                    response["HX-Trigger"] = "refreshAccessRequests"
                    return response

                if active_tab == "trust-center":
                    response = redirect(
                        reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}"
                    )
                    response["HX-Trigger"] = "refreshAccessRequests"
                    return response
                return redirect("documents:access_request_queue", team_key=team_key)

            except Invitation.DoesNotExist:
                messages.error(request, "Invitation not found")
                if active_tab == "trust-center":
                    response = redirect(
                        reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}"
                    )
                    response["HX-Trigger"] = "refreshAccessRequests"
                    return response
                return redirect("documents:access_request_queue", team_key=team_key)

        # Handle invite action (doesn't require request_id)
        if action == "invite":
            email = request.POST.get("email", "").strip()
            if not email:
                messages.error(request, "Email is required")
                if active_tab == "trust-center":
                    response = redirect(
                        reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}"
                    )
                    response["HX-Trigger"] = "refreshAccessRequests"
                    return response
                return redirect("documents:access_request_queue", team_key=team_key)

            # Check if user is already a member
            User = get_user_model()
            try:
                user = User.objects.get(email__iexact=email)
                if Member.objects.filter(team=team, user=user).exists():
                    messages.error(request, f"{email} is already a member of this workspace")
                    if active_tab == "trust-center":
                        response = redirect(
                            reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}"
                        )
                        response["HX-Trigger"] = "refreshAccessRequests"
                        return response
                    return redirect("documents:access_request_queue", team_key=team_key)
            except User.DoesNotExist:
                # User doesn't exist yet, will be created when they accept invitation
                pass

            # Check if invitation already exists (non-expired)
            existing_invitation = Invitation.objects.filter(email__iexact=email, team=team).first()
            if existing_invitation:
                if existing_invitation.has_expired:
                    existing_invitation.delete()
                else:
                    messages.error(request, f"Invitation already sent to {email}")
                    if active_tab == "trust-center":
                        response = redirect(
                            reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}"
                        )
                        response["HX-Trigger"] = "refreshAccessRequests"
                        return response
                    return redirect("documents:access_request_queue", team_key=team_key)

            # Create invitation
            invitation = Invitation.objects.create(team=team, email=email, role="guest")

            # Store inviter info in cache for later use when auto-approving access request
            # This allows us to set decided_by to the person who sent the invitation
            cache_key = f"invitation_inviter:{invitation.token}"
            cache.set(cache_key, request.user.id, timeout=60 * 60 * 24 * 7)  # 7 days (same as invitation expiry)

            # If user already exists, create/update AccessRequest with inviter set as decided_by
            try:
                invited_user = User.objects.get(email__iexact=email)
                access_request, created = AccessRequest.objects.get_or_create(
                    team=team,
                    user=invited_user,
                    defaults={
                        "status": AccessRequest.Status.PENDING,
                        "decided_by": request.user,  # Set inviter as decided_by
                    },
                )
                # If AccessRequest already exists, update decided_by if not set
                if not created and not access_request.decided_by:
                    access_request.decided_by = request.user
                    access_request.save(update_fields=["decided_by"])
            except User.DoesNotExist:
                # User doesn't exist yet, will be handled when they accept invitation
                pass

            # Send invitation email

            email_context = {
                "team": team,
                "invitation": invitation,
                "user": request.user,
                "base_url": settings.APP_BASE_URL,
            }
            send_mail(
                subject=f"Invitation to access {team.name}'s Trust Center",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                message=render_to_string("teams/emails/trust_center_invite_email.txt", email_context),
                html_message=render_to_string("teams/emails/trust_center_invite_email.html.j2", email_context),
            )

            messages.success(request, f"Invitation sent to {email}")

            # For HTMX requests, return the updated access request queue
            if request.headers.get("HX-Request") == "true":
                # Get updated requests (same logic as GET method)
                company_nda = team.get_company_nda_document()
                requires_nda = company_nda is not None

                if requires_nda:
                    signed_request_ids = NDASignature.objects.values_list("access_request_id", flat=True)
                    pending_requests = (
                        AccessRequest.objects.filter(
                            team=team, status=AccessRequest.Status.PENDING, id__in=signed_request_ids
                        )
                        .select_related("user", "decided_by")
                        .prefetch_related("nda_signature__nda_document")
                        .order_by("-requested_at")
                    )
                else:
                    pending_requests = (
                        AccessRequest.objects.filter(team=team, status=AccessRequest.Status.PENDING)
                        .select_related("user", "decided_by")
                        .prefetch_related("nda_signature__nda_document")
                        .order_by("-requested_at")
                    )

                approved_requests = (
                    AccessRequest.objects.filter(team=team, status=AccessRequest.Status.APPROVED)
                    .select_related("user", "decided_by")
                    .prefetch_related("nda_signature__nda_document")
                    .order_by("-decided_at")
                )

                # Get pending invitations
                pending_invitations_list = Invitation.objects.filter(team=team).order_by("-created_at")

                # Try to get inviter info from cache for each invitation
                invitations_with_inviter = []
                for invitation in pending_invitations_list:
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

                    invitations_with_inviter.append(
                        {
                            "invitation": invitation,
                            "inviter_email": inviter_email,
                        }
                    )

                html = render_to_string(
                    "documents/access_request_queue_content.html.j2",
                    {
                        "team": team,
                        "pending_requests": pending_requests,
                        "approved_requests": approved_requests,
                        "pending_invitations": invitations_with_inviter,
                    },
                    request=request,
                )
                response = HttpResponse(html)
                response["HX-Trigger"] = "refreshAccessRequests,closeInviteModal"
                return response

            if active_tab == "trust-center":
                response = redirect(reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}")
                response["HX-Trigger"] = "refreshAccessRequests"
                return response
            return redirect("documents:access_request_queue", team_key=team_key)

        if not action or not request_id:
            messages.error(request, "Invalid request")
            if active_tab == "trust-center":
                response = redirect(reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}")
                response["HX-Trigger"] = "refreshAccessRequests"
                return response
            return redirect("documents:access_request_queue", team_key=team_key)

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
                if active_tab == "trust-center":
                    response = redirect(
                        reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}"
                    )
                    response["HX-Trigger"] = "refreshAccessRequests"
                    return response
                return redirect("documents:access_request_queue", team_key=team_key)

            if action == "approve":
                # Check status inside transaction after locking
                if access_request.status != AccessRequest.Status.PENDING:
                    messages.error(request, "Access request is not pending")
                    if active_tab == "trust-center":
                        response = redirect(
                            reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}"
                        )
                        response["HX-Trigger"] = "refreshAccessRequests"
                        return response
                    return redirect("documents:access_request_queue", team_key=team_key)

                access_request.status = AccessRequest.Status.APPROVED
                access_request.decided_by = request.user
                access_request.decided_at = timezone.now()
                access_request.save()

                # Automatically create guest member
                Member.objects.get_or_create(
                    team=team,
                    user=access_request.user,
                    defaults={"role": "guest"},
                )  # noqa: F841 - created variable not needed

            elif action == "reject":
                # Check status inside transaction after locking
                if access_request.status != AccessRequest.Status.PENDING:
                    messages.error(request, "Access request is not pending")
                    if active_tab == "trust-center":
                        response = redirect(
                            reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}"
                        )
                        response["HX-Trigger"] = "refreshAccessRequests"
                        return response
                    return redirect("documents:access_request_queue", team_key=team_key)

                access_request.status = AccessRequest.Status.REJECTED
                access_request.decided_by = request.user
                access_request.decided_at = timezone.now()
                access_request.save()

            elif action == "revoke":
                # Check status inside transaction after locking
                if access_request.status != AccessRequest.Status.APPROVED:
                    messages.error(request, "Access request is not approved")
                    if active_tab == "trust-center":
                        response = redirect(
                            reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}"
                        )
                        response["HX-Trigger"] = "refreshAccessRequests"
                        return response
                    return redirect("documents:access_request_queue", team_key=team_key)

                access_request.status = AccessRequest.Status.REVOKED
                access_request.revoked_by = request.user
                access_request.revoked_at = timezone.now()
                access_request.save()

                # Remove guest membership
                try:
                    Member.objects.get(team=team, user=access_request.user, role="guest").delete()
                except Member.DoesNotExist:
                    # Guest member doesn't exist, nothing to remove
                    pass

            else:
                messages.error(request, "Invalid action")
                if active_tab == "trust-center":
                    response = redirect(
                        reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}"
                    )
                    response["HX-Trigger"] = "refreshAccessRequests"
                    return response
                return redirect("documents:access_request_queue", team_key=team_key)

        # Invalidate cache after transaction commits
        transaction.on_commit(lambda: _invalidate_access_requests_cache(team))

        # Handle post-transaction actions based on action type
        if action == "approve":
            # Invalidate the approved user's session cache so workspace appears immediately
            cache_key = f"user_teams_invalidate:{access_request.user.id}"
            cache.set(cache_key, True, timeout=600)  # 10 minutes should be enough

            # Send email notification to user
            try:
                login_url = reverse("core:keycloak_login")
                redirect_url = reverse("core:workspace_public", kwargs={"workspace_key": team.key})
                login_link = f"{settings.APP_BASE_URL}{login_url}?next={quote(redirect_url)}"

                email_context = {
                    "user": access_request.user,
                    "team": team,
                    "base_url": settings.APP_BASE_URL,
                    "login_link": login_link,
                }

                # Render templates first to catch template errors
                try:
                    plain_message = render_to_string("documents/emails/access_approved.txt", email_context)
                    html_message = render_to_string("documents/emails/access_approved.html.j2", email_context)
                except Exception as template_error:
                    logger.error(
                        f"Failed to render access approval email templates for "
                        f"{access_request.user.email}: {template_error}",
                        exc_info=True,
                    )
                    raise

                # Send email
                result = send_mail(
                    subject=f"Access Approved - {team.name}",
                    message=plain_message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[access_request.user.email],
                    html_message=html_message,
                    fail_silently=False,  # Don't fail silently so we can catch errors
                )
                logger.info(f"Access approval email sent to {access_request.user.email}, result: {result}")
            except Exception as e:
                logger.error(f"Failed to send access approval email to {access_request.user.email}: {e}", exc_info=True)

            messages.success(
                request,
                f"Access request approved. {access_request.user.email} now has access to "
                f"gated components as a guest member.",
            )

        elif action == "reject":
            # Send email notification to user
            try:
                email_context = {
                    "user": access_request.user,
                    "team": team,
                    "base_url": settings.APP_BASE_URL,
                }

                send_mail(
                    subject=f"Access Request Rejected - {team.name}",
                    message=render_to_string("documents/emails/access_rejected.txt", email_context),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[access_request.user.email],
                    html_message=render_to_string("documents/emails/access_rejected.html.j2", email_context),
                )
            except Exception as e:
                logger.error(f"Failed to send access rejection email to {access_request.user.email}: {e}")

            messages.success(request, "Access request rejected.")

        elif action == "revoke":
            # Invalidate the revoked user's session cache so workspace disappears immediately
            cache_key = f"user_teams_invalidate:{access_request.user.id}"
            cache.set(cache_key, True, timeout=600)  # 10 minutes should be enough

            messages.success(request, f"Access revoked for {access_request.user.email}.")

        # Dismiss notification if no more pending requests
        _dismiss_access_request_notification_if_no_pending(request, team)

        if active_tab == "trust-center":
            # Redirect to trust center tab and trigger refresh of access requests
            response = redirect(reverse("teams:team_settings", kwargs={"team_key": team_key}) + f"#{active_tab}")
            response["HX-Trigger"] = "refreshAccessRequests"
            return response
        return redirect("documents:access_request_queue", team_key=team_key)
