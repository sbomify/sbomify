"""Billing and role checks for CRA Compliance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sbomify.apps.billing.config import is_billing_enabled
from sbomify.apps.billing.models import BillingPlan

if TYPE_CHECKING:
    from django.http import HttpRequest

    from sbomify.apps.compliance.models import CRAAssessment
    from sbomify.apps.core.models import Product
    from sbomify.apps.teams.models import Team


@dataclass(frozen=True)
class AccessCheckFailure:
    """Opaque access-check failure carrying the HTTP status to return.

    ``require_assessment_access`` / ``require_product_cra_access`` return
    this on denial. The view layer translates to ``HttpResponseForbidden``
    / ``HttpResponseNotFound``; the Ninja API layer translates to the
    equivalent ``(status_code, ErrorResponse(...))``. Centralising the
    decision in one place keeps the two surfaces from drifting on a
    future role or billing rule change.

    ``error_code`` lets callers distinguish three different ``403``
    reasons (``permission_denied`` for role failures vs ``billing_gate``
    for plan failures) without pattern-matching on the human-readable
    ``message`` — the Ninja API surfaces these codes directly into its
    structured error response so clients can react programmatically.
    """

    status_code: int
    message: str
    error_code: str = "access_denied"


def check_cra_access(team: Team | None = None, *, billing_plan_key: str | None = None) -> bool:
    """Returns True if team has Business+ plan (or billing disabled).

    Pure key check — no DB query. Can be called with either a Team object
    or a billing_plan_key string from the session.
    """
    if not is_billing_enabled():
        return True
    raw_key = billing_plan_key or (team.billing_plan if team else None)
    if not raw_key:
        return False
    return raw_key.strip().lower() in BillingPlan.CRA_ELIGIBLE_PLAN_KEYS


def _is_team_member(request: HttpRequest, team_id: int) -> bool:
    """Whether the authenticated user has any role on *team_id*.

    Kept separate from role-allowlist checks so callers can distinguish
    "this user is a stranger to this team" (return 404 — don't leak
    existence) from "this user is a member but lacks the role" (return
    403 — the right UX when the caller can legitimately see the team).
    """
    if not request.user.is_authenticated:
        return False

    from sbomify.apps.teams.models import Member

    # Session cache first (avoids the DB round-trip on the hot path).
    # The session's ``user_teams`` map is keyed by team key; fall back
    # to a DB check only if it isn't populated.
    user_teams = request.session.get("user_teams") or {}
    for payload in user_teams.values():
        if payload.get("id") == team_id or payload.get("team_id") == team_id:
            return True

    return Member.objects.filter(user=request.user, team_id=team_id).exists()


def require_assessment_access(
    request: HttpRequest,
    assessment_id: str,
    *,
    allowed_roles: tuple[str, ...] = ("owner", "admin"),
) -> CRAAssessment | AccessCheckFailure:
    """Centralised access check for all CRAAssessment-bound endpoints.

    Returns the assessment on success; ``AccessCheckFailure`` otherwise.
    Both the web view and the Ninja API call this so any change to the
    role list, billing gate, or lookup semantics lands in one place.

    Access decisions:
      - Assessment missing OR user not a member of its team → 404
        (collapses both cases to the same status code so a cross-tenant
        caller cannot distinguish "does not exist" from "exists on a
        team you have no role on" via the response status alone; note
        response *timing* can still differ because the DB lookup only
        runs in the "exists" branch — the protection is on the status
        channel, not timing-resistant).
      - User is a member but role is not in ``allowed_roles`` → 403
        (the caller can legitimately know the assessment exists; the
        failure reason is the role check).
      - Team lacks the billing plan → 403.
    """
    from sbomify.apps.compliance.models import CRAAssessment
    from sbomify.apps.core.utils import verify_item_access

    # Eager-load the hot-path joins that Step 3 context builders and
    # the Ninja API consumed via a wider ``select_related`` before this
    # helper consolidated access checks. Without ``oscal_assessment_result__catalog``
    # every step render fires an extra query per request.
    try:
        assessment = CRAAssessment.objects.select_related(
            "team",
            "product",
            "oscal_assessment_result__catalog",
        ).get(pk=assessment_id)
    except CRAAssessment.DoesNotExist:
        return AccessCheckFailure(status_code=404, message="Not found", error_code="not_found")

    if not _is_team_member(request, assessment.team_id):
        return AccessCheckFailure(status_code=404, message="Not found", error_code="not_found")

    if not verify_item_access(request, assessment, list(allowed_roles)):
        return AccessCheckFailure(status_code=403, message="Forbidden", error_code="permission_denied")

    if not check_cra_access(assessment.team):
        return AccessCheckFailure(
            status_code=403,
            message="CRA access requires a Business plan",
            error_code="billing_gate",
        )

    return assessment


def require_product_cra_access(
    request: HttpRequest,
    product_id: str,
    *,
    allowed_roles: tuple[str, ...] = ("owner", "admin"),
) -> Product | AccessCheckFailure:
    """Centralised access check for Product-bound CRA endpoints.

    Same shape and intent as ``require_assessment_access``, returning
    the product on success. 404 for unknown product or non-member user;
    403 for insufficient role or missing billing plan.
    """
    from sbomify.apps.core.models import Product
    from sbomify.apps.core.utils import verify_item_access

    try:
        product = Product.objects.select_related("team").get(pk=product_id)
    except Product.DoesNotExist:
        return AccessCheckFailure(status_code=404, message="Not found", error_code="not_found")

    if not _is_team_member(request, product.team_id):
        return AccessCheckFailure(status_code=404, message="Not found", error_code="not_found")

    if not verify_item_access(request, product, list(allowed_roles)):
        return AccessCheckFailure(status_code=403, message="Forbidden", error_code="permission_denied")

    if not check_cra_access(product.team):
        return AccessCheckFailure(
            status_code=403,
            message="CRA access requires a Business plan",
            error_code="billing_gate",
        )

    return product
