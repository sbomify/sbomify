import hashlib
import logging
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from ninja import Router
from ninja.security import django_auth

from sbomify.apps.access_tokens.auth import PersonalAccessTokenAuth
from sbomify.apps.core.object_store import S3Client
from sbomify.apps.core.schemas import ErrorCode, ErrorResponse
from sbomify.apps.core.url_utils import get_base_url
from sbomify.apps.core.utils import broadcast_to_workspace, get_client_ip
from sbomify.apps.teams.models import Member, Team

from .access_models import AccessRequest, NDASignature
from .access_schemas import (
    AccessRequestCreateRequest,
    AccessRequestListResponse,
    AccessRequestResponse,
    NDASignatureResponse,
    NDASignRequest,
)

User = get_user_model()
log = logging.getLogger(__name__)

router = Router(tags=["Access Requests"], auth=(PersonalAccessTokenAuth(), django_auth))


def _invalidate_access_requests_cache(team: Team):
    """Invalidate cache for pending access requests count for all owners/admins of the team."""
    admin_members = Member.objects.filter(team=team, role__in=("owner", "admin")).values_list("user_id", flat=True)

    for user_id in admin_members:
        cache_key = f"pending_access_requests:{team.key}:{user_id}"
        cache.delete(cache_key)


def _dismiss_access_request_notification_if_no_pending(request: HttpRequest, team: Team):
    """Dismiss the access request notification if there are no more pending requests."""
    # Check if there are any pending requests left
    company_nda = team.get_company_nda_document()
    requires_nda = company_nda is not None

    if requires_nda:
        signed_request_ids = NDASignature.objects.values_list("access_request_id", flat=True)
        pending_count = AccessRequest.objects.filter(
            team=team, status=AccessRequest.Status.PENDING, id__in=signed_request_ids
        ).count()
    else:
        pending_count = AccessRequest.objects.filter(team=team, status=AccessRequest.Status.PENDING).count()

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
            log.warning(f"No admins found for team {team.key} to notify about access request {access_request.id}")
            return

        # Build email context
        requester_name = (
            f"{access_request.user.first_name} {access_request.user.last_name}".strip() or access_request.user.username
        )
        requester_email = access_request.user.email
        review_url = reverse("teams:team_settings", kwargs={"team_key": team.key})
        review_link = f"{get_base_url()}{review_url}#trust-center"

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
                    "base_url": get_base_url(),
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
                log.error(f"Failed to send access request notification to {admin_member.user.email}: {e}")

    except Exception as e:
        log.error(f"Error notifying admins of access request {access_request.id}: {e}")


@router.post(
    "/teams/{team_key}/access-request",
    response={200: dict, 201: AccessRequestResponse, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=None,  # Allow unauthenticated users to request access
)
def create_access_request(request: HttpRequest, team_key: str, payload: AccessRequestCreateRequest = None):
    """Create a blanket access request for all gated components in a team.

    Supports both authenticated and unauthenticated users.
    For unauthenticated users, creates a user account from email.
    """
    try:
        # Get team
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            return 404, {"detail": "Team not found"}

        # Get or create user
        user = None
        if request.user.is_authenticated:
            user = request.user
        else:
            if not payload or not payload.email:
                return 400, {"detail": "Email is required for unauthenticated users"}

            # Check if user already exists
            try:
                user = User.objects.get(email=payload.email)
            except User.DoesNotExist:
                # Create new user
                username = payload.email.split("@")[0]
                # Ensure username is unique
                base_username = username
                counter = 1
                while User.objects.filter(username=username).exists():
                    username = f"{base_username}_{counter}"
                    counter += 1

                user = User.objects.create_user(
                    username=username,
                    email=payload.email,
                    first_name=payload.name or "",
                )

        # Check if user already has access
        try:
            member = Member.objects.get(team=team, user=user)
            if member.role in ("owner", "admin", "guest"):
                return 200, {
                    "detail": "Already has access",
                    "access_request": None,
                }
        except Member.DoesNotExist:
            # User is not a member, continue to check for access request
            pass

        # Check if user already has approved access request
        existing_request = AccessRequest.objects.filter(
            team=team, user=user, status=AccessRequest.Status.APPROVED
        ).first()
        if existing_request:
            return 200, {"detail": "Already has access"}

        # Always check for company-wide NDA - if it exists, always require signing
        company_nda = team.get_company_nda_document()
        requires_nda = company_nda is not None

        # Check if there's a pending request
        pending_request = AccessRequest.objects.filter(
            team=team, user=user, status=AccessRequest.Status.PENDING
        ).first()
        if pending_request:
            # Check if NDA is required and not signed yet
            if requires_nda:
                has_signed = NDASignature.objects.filter(access_request=pending_request).exists()
                if not has_signed:
                    # Request exists but NDA not signed - return info that NDA signing is needed
                    return 200, {
                        "detail": "Access request exists but NDA signature required",
                        "requires_nda": True,
                        "access_request_id": str(pending_request.id),
                        "sign_nda_url": f"/workspace/{team.key}/access-request/{pending_request.id}/sign-nda",
                    }
            # Request is complete (either no NDA required or NDA already signed)
            return 400, {"detail": "Access request already pending"}

        # Create or update access request with proper race condition handling
        with transaction.atomic():
            # Use select_for_update to prevent race conditions
            existing_request = AccessRequest.objects.select_for_update().filter(team=team, user=user).first()

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

            # Invalidate cache after transaction commits
            transaction.on_commit(lambda: _invalidate_access_requests_cache(team))

            # Only send notification if NDA is not required (request is complete)
            # If NDA is required, notification will be sent after NDA is signed
            if not requires_nda:
                _notify_admins_of_access_request(access_request, team, requires_nda=False)

            # If NDA is required, return info that NDA signing is needed
            if requires_nda:
                return 201, AccessRequestResponse(
                    id=access_request.id,
                    team_id=str(team.id),
                    user_id=str(user.id),
                    status=access_request.status,
                    requested_at=access_request.requested_at.isoformat(),
                    decided_at=None,
                    decided_by_id=None,
                    revoked_at=None,
                    revoked_by_id=None,
                    notes=access_request.notes,
                ).model_dump() | {"requires_nda": True, "nda_document_id": str(company_nda.id)}

            return 201, AccessRequestResponse(
                id=access_request.id,
                team_id=str(team.id),
                user_id=str(user.id),
                status=access_request.status,
                requested_at=access_request.requested_at.isoformat(),
                decided_at=None,
                decided_by_id=None,
                revoked_at=None,
                revoked_by_id=None,
                notes=access_request.notes,
            )

    except Exception as e:
        log.error(f"Error creating access request: {e}")
        return 400, {"detail": "Invalid request"}


@router.get(
    "/teams/{team_key}/access-request/{request_id}/nda",
    response={200: None, 403: ErrorResponse, 404: ErrorResponse},
    auth=None,
)
def get_nda_for_signing(request: HttpRequest, team_key: str, request_id: str):
    """Get NDA document for signing."""
    try:
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            return 404, {"detail": "Team not found"}

        try:
            access_request = AccessRequest.objects.get(id=request_id, team=team)
        except AccessRequest.DoesNotExist:
            return 404, {"detail": "Access request not found"}

        # Verify user owns the request or is admin
        if request.user.is_authenticated:
            if access_request.user != request.user:
                # Check if user is admin/owner
                try:
                    member = Member.objects.get(team=team, user=request.user)
                    if member.role not in ("owner", "admin"):
                        return 403, {"detail": "Forbidden"}
                except Member.DoesNotExist:
                    return 403, {"detail": "Forbidden"}
        else:
            # For unauthenticated, we can't verify - allow if request is pending
            if access_request.status != AccessRequest.Status.PENDING:
                return 403, {"detail": "Forbidden"}

        # Get company-wide NDA
        company_nda = team.get_company_nda_document()
        if not company_nda:
            return 404, {"detail": "NDA document not found"}

        # Return NDA document for download
        try:
            s3 = S3Client("DOCUMENTS")
            document_data = s3.get_document_data(company_nda.document_filename)

            if document_data:
                response = HttpResponse(document_data, content_type=company_nda.content_type or "application/pdf")
                response["Content-Disposition"] = f'inline; filename="{company_nda.name}.pdf"'
                return response
            else:
                return 404, {"detail": "NDA document file not found"}

        except Exception as e:
            log.error(f"Error retrieving NDA document: {e}")
            return 500, {"detail": "Error retrieving NDA document"}

    except Exception as e:
        log.error(f"Error getting NDA for signing: {e}")
        return 400, {"detail": "Invalid request"}


@router.post(
    "/teams/{team_key}/access-request/{request_id}/sign-nda",
    response={200: NDASignatureResponse, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
    auth=None,
)
def sign_nda(request: HttpRequest, team_key: str, request_id: str, payload: NDASignRequest):
    """Sign NDA for access request."""
    try:
        try:
            team = Team.objects.get(key=team_key)
        except Team.DoesNotExist:
            return 404, {"detail": "Team not found"}

        try:
            access_request = AccessRequest.objects.get(id=request_id, team=team)
        except AccessRequest.DoesNotExist:
            return 404, {"detail": "Access request not found"}

        # Verify user owns the request
        if request.user.is_authenticated:
            if access_request.user != request.user:
                return 403, {"detail": "Forbidden"}
        else:
            # For unauthenticated, verify request is pending
            if access_request.status != AccessRequest.Status.PENDING:
                return 403, {"detail": "Forbidden"}

        # Get company-wide NDA
        company_nda = team.get_company_nda_document()
        if not company_nda:
            return 404, {"detail": "NDA document not found"}

        # Get NDA document content and calculate hash
        try:
            s3 = S3Client("DOCUMENTS")
            document_data = s3.get_document_data(company_nda.document_filename)
            nda_content_hash = hashlib.sha256(document_data).hexdigest()
        except Exception as e:
            log.error(f"Error retrieving NDA document for signing: {e}")
            return 500, {"detail": "Error retrieving NDA document"}

        # Verify document hasn't been modified (compare with stored content_hash)
        if company_nda.content_hash and nda_content_hash != company_nda.content_hash:
            log.warning(
                f"NDA document {company_nda.id} content hash mismatch during signing. "
                f"Expected: {company_nda.content_hash}, Got: {nda_content_hash}"
            )
            return 400, {"detail": "The NDA document has been modified. Please contact the workspace administrator."}

        # Validate consent - user must explicitly consent to NDA terms
        if not payload.consent:
            return 400, {
                "detail": "You must consent to the NDA terms to proceed",
                "error_code": ErrorCode.INVALID_DATA,
            }

        # Create NDA signature
        with transaction.atomic():
            nda_signature = NDASignature.objects.create(
                access_request=access_request,
                nda_document=company_nda,
                nda_content_hash=nda_content_hash,
                signed_name=payload.signed_name,
                ip_address=get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            )

            # Reload access request with NDA signature relationship
            access_request = AccessRequest.objects.prefetch_related("nda_signature").get(pk=access_request.id)

            # Now that NDA is signed, send notification to admins (request is now complete)
            # Invalidate cache after transaction commits
            transaction.on_commit(lambda: _invalidate_access_requests_cache(access_request.team))
            transaction.on_commit(
                lambda: _notify_admins_of_access_request(access_request, access_request.team, requires_nda=True)
            )

            # Broadcast to workspace for real-time UI updates (admins see new pending request)
            # Capture values for lambda closure (using different names to avoid shadowing function parameters)
            ws_team_key = access_request.team.key
            ws_request_id = str(access_request.id)
            ws_user_id = str(access_request.user.id)
            transaction.on_commit(
                lambda: broadcast_to_workspace(
                    workspace_key=ws_team_key,
                    message_type="access_request_updated",
                    data={
                        "access_request_id": ws_request_id,
                        "user_id": ws_user_id,
                        "status": "pending",
                        "action": "nda_signed",
                    },
                )
            )

            return 200, NDASignatureResponse(
                id=nda_signature.id,
                access_request_id=str(access_request.id),
                nda_document_id=str(company_nda.id),
                signed_name=nda_signature.signed_name,
                signed_at=nda_signature.signed_at.isoformat(),
            )

    except Exception as e:
        log.error(f"Error signing NDA: {e}")
        return 400, {"detail": "Invalid request"}


@router.get(
    "/access-requests/pending",
    response={200: list[AccessRequestListResponse], 403: ErrorResponse},
)
def list_pending_access_requests(request: HttpRequest):
    """List pending access requests (admin/owner only)."""
    if not request.user.is_authenticated:
        return 403, {"detail": "Authentication required"}

    # Get teams where user is owner or admin
    member_teams = Member.objects.filter(user=request.user, role__in=("owner", "admin")).values_list(
        "team_id", flat=True
    )

    if not member_teams:
        return 403, {"detail": "Access denied"}

    # Get pending requests for those teams
    # Only show requests that are complete (NDA signed if required)
    # Get teams that require NDA
    teams_requiring_nda = []
    for team_id in member_teams:
        try:
            team = Team.objects.get(pk=team_id)
            if team.get_company_nda_document():
                teams_requiring_nda.append(team_id)
        except Team.DoesNotExist:
            # Team no longer exists, skip it
            pass

    # Build query: if team requires NDA, only include requests with NDA signature
    # Base query for all pending requests
    base_query = Q(team_id__in=member_teams, status=AccessRequest.Status.PENDING)

    # For teams requiring NDA, add filter to only include signed requests
    if teams_requiring_nda:
        # Requests from teams requiring NDA must have NDA signature
        # Requests from teams not requiring NDA don't need signature
        signed_request_ids = NDASignature.objects.values_list("access_request_id", flat=True)
        nda_required_filter = Q(team_id__in=teams_requiring_nda, id__in=signed_request_ids)
        teams_not_requiring_nda = set(member_teams) - set(teams_requiring_nda)
        nda_not_required_filter = Q(team_id__in=teams_not_requiring_nda)
        base_query = base_query & (nda_required_filter | nda_not_required_filter)

    pending_requests = (
        AccessRequest.objects.filter(base_query)
        .select_related("team", "user", "decided_by")
        .prefetch_related("nda_signature__nda_document")
        .order_by("-requested_at")
    )

    results = []
    for req in pending_requests:
        # Check if NDA signature exists using prefetched data
        # getattr with default None is safe and uses prefetched relationship
        has_nda = bool(getattr(req, "nda_signature", None))
        results.append(
            AccessRequestListResponse(
                id=req.id,
                team_id=str(req.team.id),
                team_name=req.team.name,
                user_id=str(req.user.id),
                user_email=req.user.email,
                user_name=f"{req.user.first_name} {req.user.last_name}".strip() or None,
                status=req.status,
                requested_at=req.requested_at.isoformat(),
                decided_at=req.decided_at.isoformat() if req.decided_at else None,
                decided_by_id=str(req.decided_by.id) if req.decided_by else None,
                decided_by_email=req.decided_by.email if req.decided_by else None,
                has_nda_signature=has_nda,
                notes=req.notes,
            )
        )

    return 200, results


@router.post(
    "/access-requests/{request_id}/approve",
    response={200: AccessRequestResponse, 400: ErrorResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def approve_access_request(request: HttpRequest, request_id: str):
    """Approve access request and automatically add user as guest member (admin/owner only)."""
    if not request.user.is_authenticated:
        return 403, {"detail": "Authentication required"}

    with transaction.atomic():
        # Lock the access request row to prevent race conditions
        try:
            access_request = AccessRequest.objects.select_for_update().select_related("team", "user").get(id=request_id)
        except AccessRequest.DoesNotExist:
            return 404, {"detail": "Access request not found"}

        # Verify user is owner or admin of the team
        try:
            member = Member.objects.get(team=access_request.team, user=request.user)
            if member.role not in ("owner", "admin"):
                return 403, {"detail": "Access denied"}
        except Member.DoesNotExist:
            return 403, {"detail": "Access denied"}

        # Check status inside transaction after locking
        if access_request.status != AccessRequest.Status.PENDING:
            return 400, {"detail": "Access request is not pending"}

        # Update access request
        access_request.status = AccessRequest.Status.APPROVED
        access_request.decided_by = request.user
        access_request.decided_at = timezone.now()
        access_request.save()

        # Automatically create guest member
        Member.objects.get_or_create(
            team=access_request.team,
            user=access_request.user,
            defaults={"role": "guest"},
        )

    # Cache invalidation and email sending outside transaction
    # Invalidate cache after transaction commits
    transaction.on_commit(lambda: _invalidate_access_requests_cache(access_request.team))

    # Invalidate the approved user's session cache so workspace appears immediately
    cache_key = f"user_teams_invalidate:{access_request.user.id}"
    cache.set(cache_key, True, timeout=600)  # 10 minutes should be enough

    # Send email notification to user (outside transaction)
    try:
        login_url = reverse("core:keycloak_login")
        redirect_url = reverse("core:workspace_public", kwargs={"workspace_key": access_request.team.key})
        login_link = f"{get_base_url()}{login_url}?next={quote(redirect_url)}"

        email_context = {
            "user": access_request.user,
            "team": access_request.team,
            "base_url": get_base_url(),
            "login_link": login_link,
        }

        # Render templates first to catch template errors
        try:
            plain_message = render_to_string("documents/emails/access_approved.txt", email_context)
            html_message = render_to_string("documents/emails/access_approved.html.j2", email_context)
        except Exception as template_error:
            log.error(
                f"Failed to render access approval email templates for {access_request.user.email}: {template_error}",
                exc_info=True,
            )
            raise

        # Send email
        result = send_mail(
            subject=f"Access Approved - {access_request.team.name}",
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[access_request.user.email],
            html_message=html_message,
            fail_silently=False,  # Don't fail silently so we can catch errors
        )
        log.info(f"Access approval email sent to {access_request.user.email}, result: {result}")
    except Exception as e:
        log.error(f"Failed to send access approval email to {access_request.user.email}: {e}", exc_info=True)

    # Dismiss notification if no more pending requests
    _dismiss_access_request_notification_if_no_pending(request, access_request.team)

    # Broadcast to workspace for real-time UI updates
    # This notifies both:
    # 1. The requester's browser to update their access status on public pages
    # 2. Admins' browsers to update the access request queue
    broadcast_to_workspace(
        workspace_key=access_request.team.key,
        message_type="access_request_updated",
        data={
            "access_request_id": str(access_request.id),
            "user_id": str(access_request.user.id),
            "status": "approved",
            "action": "approved",
        },
    )

    return 200, AccessRequestResponse(
        id=access_request.id,
        team_id=str(access_request.team.id),
        user_id=str(access_request.user.id),
        status=access_request.status,
        requested_at=access_request.requested_at.isoformat(),
        decided_at=access_request.decided_at.isoformat(),
        decided_by_id=str(access_request.decided_by.id),
        revoked_at=None,
        revoked_by_id=None,
        notes=access_request.notes,
    )


@router.post(
    "/access-requests/{request_id}/reject",
    response={200: AccessRequestResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def reject_access_request(request: HttpRequest, request_id: str):
    """Reject access request (admin/owner only)."""
    if not request.user.is_authenticated:
        return 403, {"detail": "Authentication required"}

    with transaction.atomic():
        # Lock the access request row to prevent race conditions
        try:
            access_request = AccessRequest.objects.select_for_update().select_related("team", "user").get(id=request_id)
        except AccessRequest.DoesNotExist:
            return 404, {"detail": "Access request not found"}

        # Verify user is owner or admin of the team
        try:
            member = Member.objects.get(team=access_request.team, user=request.user)
            if member.role not in ("owner", "admin"):
                return 403, {"detail": "Access denied"}
        except Member.DoesNotExist:
            return 403, {"detail": "Access denied"}

        # Check status inside transaction after locking
        if access_request.status != AccessRequest.Status.PENDING:
            return 400, {"detail": "Access request is not pending"}

        # Delete NDA signature so user must sign again when requesting access
        if hasattr(access_request, "nda_signature"):
            access_request.nda_signature.delete()

        access_request.status = AccessRequest.Status.REJECTED
        access_request.decided_by = request.user
        access_request.decided_at = timezone.now()
        access_request.save()

    # Invalidate cache after transaction commits
    transaction.on_commit(lambda: _invalidate_access_requests_cache(access_request.team))

    # Send email notification to user
    try:
        email_context = {
            "user": access_request.user,
            "team": access_request.team,
            "base_url": get_base_url(),
        }

        send_mail(
            subject=f"Access Request Rejected - {access_request.team.name}",
            message=render_to_string("documents/emails/access_rejected.txt", email_context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[access_request.user.email],
            html_message=render_to_string("documents/emails/access_rejected.html.j2", email_context),
        )
    except Exception as e:
        log.error(f"Failed to send access rejection email to {access_request.user.email}: {e}")

    # Dismiss notification if no more pending requests
    _dismiss_access_request_notification_if_no_pending(request, access_request.team)

    # Broadcast to workspace for real-time UI updates
    broadcast_to_workspace(
        workspace_key=access_request.team.key,
        message_type="access_request_updated",
        data={
            "access_request_id": str(access_request.id),
            "user_id": str(access_request.user.id),
            "status": "rejected",
            "action": "rejected",
        },
    )

    return 200, AccessRequestResponse(
        id=access_request.id,
        team_id=str(access_request.team.id),
        user_id=str(access_request.user.id),
        status=access_request.status,
        requested_at=access_request.requested_at.isoformat(),
        decided_at=access_request.decided_at.isoformat(),
        decided_by_id=str(access_request.decided_by.id),
        revoked_at=None,
        revoked_by_id=None,
        notes=access_request.notes,
    )


@router.post(
    "/access-requests/{request_id}/revoke",
    response={200: AccessRequestResponse, 403: ErrorResponse, 404: ErrorResponse},
)
def revoke_access_request(request: HttpRequest, request_id: str):
    """Revoke access request and remove guest membership (admin/owner only)."""
    if not request.user.is_authenticated:
        return 403, {"detail": "Authentication required"}

    with transaction.atomic():
        # Lock the access request row to prevent race conditions
        try:
            access_request = AccessRequest.objects.select_for_update().select_related("team", "user").get(id=request_id)
        except AccessRequest.DoesNotExist:
            return 404, {"detail": "Access request not found"}

        # Verify user is owner or admin of the team
        try:
            member = Member.objects.get(team=access_request.team, user=request.user)
            if member.role not in ("owner", "admin"):
                return 403, {"detail": "Access denied"}
        except Member.DoesNotExist:
            return 403, {"detail": "Access denied"}

        # Check status inside transaction after locking
        if access_request.status != AccessRequest.Status.APPROVED:
            return 400, {"detail": "Access request is not approved"}

        # Delete NDA signature so user must sign again when requesting access
        if hasattr(access_request, "nda_signature"):
            access_request.nda_signature.delete()

        # Update access request
        access_request.status = AccessRequest.Status.REVOKED
        access_request.revoked_by = request.user
        access_request.revoked_at = timezone.now()
        access_request.save()

        # Remove guest membership
        try:
            guest_member = Member.objects.get(team=access_request.team, user=access_request.user, role="guest")
            guest_member.delete()
        except Member.DoesNotExist:
            # Guest member doesn't exist, nothing to remove
            pass

    # Cache invalidation outside transaction
    # Invalidate cache after transaction commits
    transaction.on_commit(lambda: _invalidate_access_requests_cache(access_request.team))

    # Invalidate the revoked user's session cache so workspace disappears immediately
    cache_key = f"user_teams_invalidate:{access_request.user.id}"
    cache.set(cache_key, True, timeout=600)  # 10 minutes should be enough

    # Send email notification to user
    try:
        email_context = {
            "user": access_request.user,
            "team": access_request.team,
            "base_url": get_base_url(),
        }

        send_mail(
            subject=f"Access Revoked - {access_request.team.name}",
            message=render_to_string("documents/emails/access_revoked.txt", email_context),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[access_request.user.email],
            html_message=render_to_string("documents/emails/access_revoked.html.j2", email_context),
        )
    except Exception as e:
        log.error(f"Failed to send access revocation email to {access_request.user.email}: {e}")

    # Broadcast to workspace for real-time UI updates
    broadcast_to_workspace(
        workspace_key=access_request.team.key,
        message_type="access_request_updated",
        data={
            "access_request_id": str(access_request.id),
            "user_id": str(access_request.user.id),
            "status": "revoked",
            "action": "revoked",
        },
    )

    return 200, AccessRequestResponse(
        id=access_request.id,
        team_id=str(access_request.team.id),
        user_id=str(access_request.user.id),
        status=access_request.status,
        requested_at=access_request.requested_at.isoformat(),
        decided_at=access_request.decided_at.isoformat() if access_request.decided_at else None,
        decided_by_id=str(access_request.decided_by.id) if access_request.decided_by else None,
        revoked_at=access_request.revoked_at.isoformat(),
        revoked_by_id=str(access_request.revoked_by.id),
        notes=access_request.notes,
    )
