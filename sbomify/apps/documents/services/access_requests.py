"""State changes of a trust-center access request.

The HTMX views (``documents.views.access_requests``) and the API
(``documents.access_apis``) move the same request through the same states.
Each entry point keeps its own checks, responses and events; the changes
themselves live here once, as the emails do in ``services.access_emails``.
The functions that change a request expect the caller to hold its row lock
inside a transaction.
"""

from __future__ import annotations

from django.core.cache import cache
from django.db import IntegrityError
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone

from sbomify.apps.core.authz import ADMINISTER, READ_INTERNAL, ROLE_GUEST
from sbomify.apps.core.models import User
from sbomify.apps.core.utils import get_client_ip
from sbomify.apps.documents.access_models import AccessRequest, NDASignature
from sbomify.apps.documents.models import Document
from sbomify.apps.teams.models import Member, Team

# Anyone already in the workspace, internal or external — they do not need to
# ask for access they already have.
ANY_MEMBER_ROLES = READ_INTERNAL + (ROLE_GUEST,)


def invalidate_access_requests_cache(team: Team) -> None:
    """Invalidate cache for pending access requests count for all owners/admins of the team."""
    admin_members = Member.objects.filter(team=team, role__in=ADMINISTER).values_list("user_id", flat=True)

    for user_id in admin_members:
        cache_key = f"pending_access_requests:{team.key}:{user_id}"
        cache.delete(cache_key)


def pending_access_requests(team: Team) -> QuerySet[AccessRequest]:
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
        .prefetch_related("nda_signatures__nda_document")
        .order_by("-requested_at")
    )

    if requires_nda:
        # Only show requests that have NDA signature (request is complete)
        signed_request_ids = NDASignature.objects.live().values_list("access_request_id", flat=True).distinct()
        return base_queryset.filter(id__in=signed_request_ids)

    return base_queryset


def dismiss_access_request_notification_if_no_pending(request: HttpRequest, team: Team) -> None:
    """Dismiss the access request notification if there are no more pending requests."""
    if pending_access_requests(team).count() == 0:
        notification_id = f"access_request_pending_{team.key}"
        dismissed_ids = set(request.session.get("dismissed_notifications", []))
        dismissed_ids.add(notification_id)
        request.session["dismissed_notifications"] = list(dismissed_ids)
        request.session.save()


def request_access(team: Team, user: User) -> tuple[AccessRequest, bool]:
    """The user's request for the workspace, created, or reopened as pending.

    Returns the request and whether this changed its state: a new request, or a
    rejected or revoked one asked again. A pending or approved request comes
    back untouched.
    """
    existing_request = AccessRequest.objects.select_for_update().filter(team=team, user=user).first()
    if existing_request:
        if existing_request.status in (AccessRequest.Status.REVOKED, AccessRequest.Status.REJECTED):
            existing_request.reopen()
            return existing_request, True
        return existing_request, False

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
        return access_request, created
    except IntegrityError:
        # Race condition: another request was created between check and create
        try:
            return AccessRequest.objects.get(team=team, user=user), False
        except AccessRequest.DoesNotExist:
            # Extremely rare: row was deleted between IntegrityError and get(). Retry once; a
            # row this creates is a state change like any other.
            return AccessRequest.objects.get_or_create(
                team=team, user=user, defaults={"status": AccessRequest.Status.PENDING}
            )


def record_nda_signature(
    request: HttpRequest, access_request: AccessRequest, nda: Document, content_hash: str, signed_name: str
) -> tuple[NDASignature, AccessRequest]:
    """Record the requester's acceptance of ``nda``; returns it and the request reloaded with its signatures.

    A signature for an earlier NDA version stays untouched: each row is the
    record of one acceptance, and signing the current version adds to that
    history rather than rewriting it.
    """
    signature = NDASignature.objects.create(
        access_request=access_request,
        nda_document=nda,
        nda_content_hash=content_hash,
        signed_name=signed_name,
        ip_address=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )
    return signature, AccessRequest.objects.prefetch_related("nda_signatures").get(pk=access_request.id)


def approve_request(access_request: AccessRequest, decided_by: User) -> None:
    """Grant a pending request and make the requester a guest of the workspace."""
    access_request.status = AccessRequest.Status.APPROVED
    access_request.decided_by = decided_by
    access_request.decided_at = timezone.now()
    access_request.save()

    Member.objects.get_or_create(team=access_request.team, user=access_request.user, defaults={"role": "guest"})


def reject_request(access_request: AccessRequest, decided_by: User) -> None:
    """Refuse a pending request.

    The live signature is superseded so a re-request must sign again; the row
    itself is the record of what was accepted and survives.
    """
    access_request.nda_signatures.live().update(superseded_at=timezone.now())

    access_request.status = AccessRequest.Status.REJECTED
    access_request.decided_by = decided_by
    access_request.decided_at = timezone.now()
    access_request.save()


def revoke_request(access_request: AccessRequest, revoked_by: User) -> None:
    """Withdraw granted access, and the guest membership that came with it.

    The live signature is superseded so a re-request must sign again; the row
    itself is the record of what was accepted and survives.
    """
    access_request.nda_signatures.live().update(superseded_at=timezone.now())

    access_request.status = AccessRequest.Status.REVOKED
    access_request.revoked_by = revoked_by
    access_request.revoked_at = timezone.now()
    access_request.save()

    try:
        Member.objects.get(team=access_request.team, user=access_request.user, role="guest").delete()
    except Member.DoesNotExist:
        # Guest member doesn't exist, nothing to remove
        pass
