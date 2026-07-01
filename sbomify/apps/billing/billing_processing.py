"""
Module for handling Stripe billing webhook events and related processing
"""

from __future__ import annotations

import datetime
from enum import Enum
from functools import wraps
from typing import Any, NoReturn

from django.conf import settings
from django.db import models, transaction
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.utils import timezone

from sbomify.apps.core.queries import get_team_asset_count, get_team_asset_counts
from sbomify.apps.teams.models import Team
from sbomify.logging import getLogger

from . import email_notifications
from .billing_helpers import (
    generate_webhook_id,
    get_community_plan_limits,
    handle_community_downgrade_visibility,
    notify_team_owners,
    parse_cancel_at,
)
from .config import get_unlimited_plan_limits, is_billing_enabled
from .models import BillingPlan
from .stripe_cache import get_subscription_cancel_at_period_end, invalidate_subscription_cache
from .stripe_client import BillingRetryableError, StripeError, get_stripe_client, handle_stripe_errors

logger = getLogger(__name__)

stripe_client = get_stripe_client()


def _best_effort(description: str, fn: Any, *args: Any, **kwargs: Any) -> None:
    """Run a non-billing-critical side effect (cache invalidation, notifications, analytics)
    without failing the webhook.

    These run alongside — usually after — the billing-state write, which is the only part
    that must be durable. A transient failure here must not raise: a 5xx would trigger a
    retry that the idempotency guard then skips, so the side effect is lost either way and
    the retry is futile. Log and move on; the cache is short-TTL self-healing and the
    billing state is reconciled by subsequent Stripe events / the trial-sync cron.
    """
    try:
        fn(*args, **kwargs)
    except Exception as e:
        logger.warning("Non-critical side effect failed (%s): %s", description, e)


def _raise_classified_webhook_error(exc: Exception) -> NoReturn:
    """Single source of truth for the webhook retryable/terminal contract.

    Every webhook handler funnels its failures through here so the 200-vs-5xx policy
    lives in one place instead of being hand-rolled (and drifting) across handlers:

    * ``BillingRetryableError`` (incl. transient Stripe failures surfaced by the
      ``handle_stripe_errors`` decorator) -> propagate so the view returns 5xx and
      Stripe retries.
    * ``Team.DoesNotExist`` / an explicit terminal ``StripeError`` (e.g. an invalid
      subscription status, or a terminal Stripe failure such as a missing customer)
      -> terminal: the view acknowledges with 200.
    * Anything else (unexpected) -> retryable, so a transient bug/outage is not
      silently dropped.
    """
    if isinstance(exc, BillingRetryableError):
        raise exc
    if isinstance(exc, Team.DoesNotExist):
        # Terminal: a genuinely nonexistent team cannot be conjured by a retry.
        raise StripeError(str(exc) or "No team found for webhook event") from exc
    if isinstance(exc, StripeError):
        # Explicit terminal business error or a terminal Stripe failure — preserve it.
        raise exc
    # Don't log here: the webhook view logs this (with exc_info) when it returns 5xx,
    # so logging again would double the stack trace. Keep the message generic; the
    # original exception (with any Stripe identifiers) stays in the chained traceback.
    raise BillingRetryableError(f"Unexpected error processing webhook event ({type(exc).__name__})") from exc


class BillingResourceType(str, Enum):
    """Resource types that are subject to billing limits."""

    PRODUCT = "product"
    COMPONENT = "component"


# Set of valid billing resource type values for quick validation
BILLING_RESOURCE_TYPES = {rt.value for rt in BillingResourceType}

# Mapping from resource type to BillingPlan field name for limits
RESOURCE_TYPE_TO_LIMIT_FIELD = {
    BillingResourceType.PRODUCT.value: "max_products",
    BillingResourceType.COMPONENT.value: "max_components",
}


def get_resource_limit(plan: BillingPlan, resource_type: str) -> int | None:
    """Get the limit for a resource type from a billing plan."""
    field_name = RESOURCE_TYPE_TO_LIMIT_FIELD.get(resource_type)
    if field_name:
        return getattr(plan, field_name, None)
    return None


def _billing_error_response(request: HttpRequest, message: str, status: int = 403) -> HttpResponse:
    """Return a JSON or HTML error response based on request type."""
    is_ajax = (
        request.headers.get("Accept") == "application/json"
        or request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest"
    )
    if is_ajax:
        return JsonResponse({"error": message, "limit_reached": True}, status=status)
    return HttpResponseForbidden(message)


def check_billing_limits(resource_type: str) -> Any:
    """
    Decorator to check if a team has reached their billing plan limits.

    Args:
        resource_type: Type of resource being created. Must be one of: 'product' or 'component'
    """

    def decorator(view_func: Any) -> Any:
        @wraps(view_func)
        def _wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
            if request.method != "POST":
                return view_func(request, *args, **kwargs)

            if not is_billing_enabled():
                return view_func(request, *args, **kwargs)

            team_key = request.session.get("current_team", {}).get("key")
            if not team_key:
                return HttpResponseForbidden("No team selected")

            try:
                team = Team.objects.get(key=team_key)
            except Team.DoesNotExist:
                return HttpResponseForbidden("Workspace not found")

            if not team.billing_plan:
                return HttpResponseForbidden("No active billing plan")

            with transaction.atomic():
                team = Team.objects.select_for_update().get(pk=team.pk)
                billing_limits = team.billing_plan_limits or {}
                subscription_status = billing_limits.get("subscription_status")

                cancel_at_period_end = billing_limits.get("cancel_at_period_end", False)
                scheduled_downgrade_plan = billing_limits.get("scheduled_downgrade_plan")
                stripe_subscription_id = billing_limits.get("stripe_subscription_id")

                if cancel_at_period_end and scheduled_downgrade_plan:
                    sub_id = str(stripe_subscription_id) if stripe_subscription_id else ""
                    real_cancel_at_period_end = get_subscription_cancel_at_period_end(
                        sub_id, team.key or "", fallback_value=bool(cancel_at_period_end)
                    )

                    if not real_cancel_at_period_end:
                        billing_limits = billing_limits.copy()
                        billing_limits.pop("scheduled_downgrade_plan", None)
                        if stripe_subscription_id:
                            invalidate_subscription_cache(str(stripe_subscription_id), team.key)
                        team.billing_plan_limits = billing_limits
                        team.save()
                        logger.info("User reactivated subscription, cleared scheduled downgrade")
                    else:
                        try:
                            target_plan = BillingPlan.objects.get(key=scheduled_downgrade_plan)
                        except BillingPlan.DoesNotExist:
                            logger.warning("Target plan not found for scheduled downgrade, skipping check")
                        else:
                            max_allowed = get_resource_limit(target_plan, resource_type)

                            if max_allowed is not None:
                                current_count = get_team_asset_count(str(team.id), resource_type)
                                if (current_count + 1) > max_allowed:
                                    error_message = (
                                        f"You cannot create this {resource_type} because your scheduled downgrade to "
                                        f"{target_plan.name} would exceed the plan limit of "
                                        f"{max_allowed} {resource_type}s. "
                                        "Please reduce your usage or continue with your current plan."
                                    )
                                    return _billing_error_response(request, error_message)

                if subscription_status == "past_due":
                    failed_at_str = billing_limits.get("payment_failed_at")

                    if not failed_at_str:
                        # A past_due subscription with no recorded failure time would otherwise
                        # skip the grace check entirely and escape enforcement. Stamp it now so
                        # the grace window starts (persisted — team is select_for_update'd here).
                        failed_at_str = timezone.now().isoformat()
                        billing_limits = billing_limits.copy()
                        billing_limits["payment_failed_at"] = failed_at_str
                        team.billing_plan_limits = billing_limits
                        team.save(update_fields=["billing_plan_limits"])

                    try:
                        failed_at = datetime.datetime.fromisoformat(failed_at_str.replace("Z", "+00:00"))
                        delta = timezone.now() - failed_at
                        grace_days = getattr(settings, "PAYMENT_GRACE_PERIOD_DAYS", 3)
                        grace_period_seconds = grace_days * 24 * 60 * 60

                        if delta.total_seconds() > grace_period_seconds:
                            msg = (
                                "Payment failed. Grace period expired. "
                                "Please update payment method to create resources."
                            )
                            logger.warning("Blocking resource access: Grace period expired")
                            return _billing_error_response(request, msg)

                    except (ValueError, TypeError):
                        logger.error("Invalid payment_failed_at format")
                        msg = "Payment failed. Unable to verify grace period. Please contact support."
                        return _billing_error_response(request, msg)

            try:
                plan = BillingPlan.objects.get(key=team.billing_plan)
            except BillingPlan.DoesNotExist:
                return HttpResponseForbidden("Invalid billing plan")

            if resource_type not in BILLING_RESOURCE_TYPES:
                return HttpResponseForbidden("Invalid resource type")

            max_allowed = get_resource_limit(plan, resource_type)

            current_count = get_team_asset_count(str(team.id), resource_type)

            if plan.key == "enterprise" or max_allowed is None:
                return view_func(request, *args, **kwargs)

            if current_count >= max_allowed:
                error_message = f"You have reached the maximum {max_allowed} {resource_type}s allowed by your plan"
                return _billing_error_response(request, error_message)

            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


@handle_stripe_errors
def handle_trial_period(subscription: Any, team: Team) -> bool:
    """Handle trial period status and notifications."""
    if subscription.status == "trialing" and subscription.trial_end:
        trial_end_value = subscription.trial_end

        try:
            trial_end = datetime.datetime.fromtimestamp(int(trial_end_value), tz=datetime.timezone.utc)
            days_remaining = (trial_end - timezone.now()).days
        except (TypeError, ValueError, OSError) as e:
            logger.warning(f"Could not convert trial_end to datetime: {e}")
            return False

        with transaction.atomic():
            team = Team.objects.select_for_update().get(pk=team.pk)
            billing_limits = (team.billing_plan_limits or {}).copy()
            billing_limits.update(
                {"is_trial": True, "trial_end": subscription.trial_end, "trial_days_remaining": days_remaining}
            )
            team.billing_plan_limits = billing_limits
            team.save()

        if days_remaining <= settings.TRIAL_ENDING_NOTIFICATION_DAYS:
            notify_team_owners(team, email_notifications.notify_trial_ending, days_remaining)
            logger.info("Trial ending notification sent")

        if days_remaining <= 0:
            # See ``TrialExpiryEmissionGuard`` for the two-marker state machine
            # that makes the side effects below crash-tolerant and idempotent
            # across concurrent / redelivered webhooks.
            from sbomify.apps.billing.trial_expiry import TrialExpiryEmissionGuard

            guard = TrialExpiryEmissionGuard()
            now = timezone.now()
            with transaction.atomic():
                team = Team.objects.select_for_update().get(pk=team.pk)
                billing_limits = (team.billing_plan_limits or {}).copy()
                should_run_side_effects = guard.should_claim(billing_limits, now)
                billing_limits.update({"is_trial": False, "subscription_status": "canceled"})
                team.billing_plan = "community"
                billing_limits.update(get_community_plan_limits())
                if should_run_side_effects:
                    guard.stamp_claim(billing_limits, now)
                team.billing_plan_limits = billing_limits
                team.save()

            if should_run_side_effects:
                handle_community_downgrade_visibility(team)
                notify_team_owners(team, email_notifications.notify_trial_expired)
                logger.info("Trial expired — downgraded team %s to community plan", team.key)

                # Signal/background context: no request, so consent is not gated here.
                # Distinct_id = team_key matches the Tier 1 signal pattern at
                # sbomify/apps/core/signals.py (sbom:uploaded, document:uploaded) for
                # consistent workspace-level attribution across tiers.
                team_key = team.key or ""
                distinct_id = team_key or "system"

                # Stamp the completion marker FIRST, defer the PostHog capture
                # via ``transaction.on_commit`` so the marker is durable before
                # the event fires. See ``TrialExpiryEmissionGuard`` for why
                # marker-then-event (vs. event-then-marker) is the correct
                # crash-tolerance ordering.
                with transaction.atomic():
                    team = Team.objects.select_for_update().get(pk=team.pk)
                    billing_limits = (team.billing_plan_limits or {}).copy()
                    guard.stamp_emitted(billing_limits, timezone.now())
                    team.billing_plan_limits = billing_limits
                    team.save()

                    from sbomify.apps.core.posthog_service import capture

                    transaction.on_commit(
                        lambda: capture(
                            distinct_id,
                            "billing:trial_expired",
                            {"team_key": team_key},
                            groups={"workspace": team_key} if team_key else None,
                        )
                    )

        return True
    return False


@handle_stripe_errors
def handle_subscription_updated(subscription: Any, event: Any = None) -> None:
    """Handle subscription updated events.

    Args:
        subscription: Stripe subscription object
        event: Optional Stripe event object for idempotency checking
    """
    try:
        team, billing_limits = _resolve_team_from_subscription(subscription)

        valid_statuses = ["trialing", "active", "past_due", "canceled", "incomplete", "incomplete_expired"]
        if subscription.status not in valid_statuses:
            raise StripeError(f"Invalid subscription status: {subscription.status}")

        webhook_id = generate_webhook_id(event, subscription, prefix="sub")
        last_processed_id = billing_limits.get("last_processed_webhook_id")

        if last_processed_id == webhook_id:
            logger.info("Webhook already processed, skipping")
            return

        _best_effort("subscription cache invalidation", invalidate_subscription_cache, subscription.id, team.key)

        previous_status = billing_limits.get("subscription_status")
        billing_limits = _update_billing_from_subscription(team, subscription, webhook_id)

        _best_effort(
            "subscription updated notifications",
            _send_subscription_notifications,
            team,
            subscription.status,
            previous_status,
        )

        from sbomify.apps.core.posthog_service import capture, group_identify

        workspace_key = team.key
        distinct_id = workspace_key or "system"
        capture(
            distinct_id,
            "billing:subscription_updated",
            {
                "status": subscription.status,
                "previous_status": previous_status or "",
                "plan": team.billing_plan or "",
            },
            groups={"workspace": workspace_key} if workspace_key else None,
        )
        if workspace_key:
            group_identify(
                "workspace",
                workspace_key,
                {"billing_plan": team.billing_plan, "subscription_status": subscription.status},
            )

        logger.info(f"Updated subscription status to {subscription.status}")

    except Exception as e:
        _raise_classified_webhook_error(e)


def _resolve_team_from_subscription(subscription: Any) -> tuple[Team, dict[str, Any]]:
    """Resolve Team from subscription using multiple lookup strategies.

    Returns:
        Tuple of (team, billing_limits)
    """
    try:
        team = Team.objects.get(billing_plan_limits__stripe_subscription_id=subscription.id)
        return team, team.billing_plan_limits or {}
    except Team.DoesNotExist:
        pass

    try:
        team = Team.objects.get(billing_plan_limits__stripe_customer_id=subscription.customer)
        logger.warning("Found team by customer ID instead of subscription ID")
        return team, team.billing_plan_limits or {}
    except Team.DoesNotExist:
        pass

    # Last resort: recover the team via the Stripe customer's metadata. A *transient*
    # Stripe outage here must be retried (BillingRetryableError); a *permanent* failure
    # (e.g. no such customer) cannot be resolved by retrying, so fall through to the
    # terminal "no team" path rather than amplifying futile retries.
    try:
        customer = stripe_client.get_customer(subscription.customer)
    except BillingRetryableError:
        raise
    except StripeError:
        # Don't log the Stripe customer/subscription identifiers here (flagged as
        # sensitive by code scanning); the subscription id is still carried in the
        # terminal Team.DoesNotExist raised below.
        logger.warning("Permanent failure fetching Stripe customer during team resolution; treating as no team")
        customer = None

    if customer is not None and customer.metadata and "team_key" in customer.metadata:
        try:
            team = Team.objects.get(key=customer.metadata["team_key"])
        except Team.DoesNotExist:
            pass
        else:
            logger.warning("Found team by customer metadata")
            return team, team.billing_plan_limits or {}

    # Definitively unresolved after every strategy → terminal "no team". Keep the
    # message free of the Stripe subscription id (re-logged by the webhook view).
    raise Team.DoesNotExist("No team found for the subscription in this webhook event")


def _update_billing_from_subscription(team: Team, subscription: Any, webhook_id: str) -> dict[str, Any]:
    """Update team billing limits from subscription data within a transaction.

    Returns:
        The updated billing_limits dict.
    """
    with transaction.atomic():
        team = Team.objects.select_for_update().get(pk=team.pk)
        billing_limits: dict[str, Any] = (team.billing_plan_limits or {}).copy()

        if billing_limits.get("last_processed_webhook_id") == webhook_id:
            logger.info("Webhook already processed (checked after lock)")
            return billing_limits

        billing_limits["subscription_status"] = subscription.status
        billing_limits["stripe_subscription_id"] = subscription.id
        billing_limits["last_updated"] = timezone.now().isoformat()
        billing_limits["last_processed_webhook_id"] = webhook_id

        from .stripe_sync import get_period_end_from_subscription

        next_billing_date = get_period_end_from_subscription(subscription, subscription.id)
        if next_billing_date:
            billing_limits["next_billing_date"] = next_billing_date

        previous_cancel_at_period_end = billing_limits.get("cancel_at_period_end", False)
        new_cancel_at_period_end = getattr(subscription, "cancel_at_period_end", False)
        cancel_at = getattr(subscription, "cancel_at", None)

        if parse_cancel_at(cancel_at) is not None:
            new_cancel_at_period_end = True
            logger.debug("cancel_at is set, treating as scheduled cancellation")

        if hasattr(subscription, "cancel_at_period_end") or cancel_at:
            billing_limits["cancel_at_period_end"] = new_cancel_at_period_end

            if not previous_cancel_at_period_end and new_cancel_at_period_end:
                if not billing_limits.get("scheduled_downgrade_plan"):
                    billing_limits["scheduled_downgrade_plan"] = "community"
                    logger.info("set scheduled_downgrade_plan to community")

            elif previous_cancel_at_period_end and not new_cancel_at_period_end:
                billing_limits.pop("scheduled_downgrade_plan", None)
                logger.info("User reactivated subscription, cleared scheduled downgrade")

        if billing_limits.get("stripe_subscription_id") and not billing_limits.get("stripe_customer_id"):
            if hasattr(subscription, "customer"):
                billing_limits["stripe_customer_id"] = subscription.customer
                logger.info("Setting missing stripe_customer_id from subscription")
            else:
                logger.warning("Could not find customer ID in subscription")

        # Real StripeObjects subclass dict, so ``subscription.items`` resolves to the
        # dict METHOD rather than the line-item list. Read items via subscript access
        # for dict-like payloads; fall back to attribute access for plain objects.
        if isinstance(subscription, dict):
            items_obj = subscription.get("items")
        else:
            items_obj = getattr(subscription, "items", None)
        items_data = None
        if items_obj is not None:
            items_data = items_obj.get("data") if isinstance(items_obj, dict) else getattr(items_obj, "data", None)

        if items_data:
            try:
                found_plan = None

                for item in items_data:
                    price_id = item.price.id
                    try:
                        found_plan = BillingPlan.objects.filter(
                            models.Q(stripe_price_monthly_id=price_id) | models.Q(stripe_price_annual_id=price_id)
                        ).first()
                        if found_plan:
                            break
                    except Exception as e:
                        logger.warning(f"Error resolving plan by price ID {price_id}: {e}")
                        continue

                if found_plan:
                    plan = found_plan
                else:
                    plan_key = subscription.metadata.get("plan_key", "business")
                    logger.warning("Could not find plan by price ID, falling back to metadata key")
                    plan = BillingPlan.objects.get(key=plan_key)

                team.billing_plan = plan.key
                billing_limits.update(
                    {
                        "max_products": plan.max_products,
                        "max_components": plan.max_components,
                    }
                )
            except BillingPlan.DoesNotExist as e:
                # Persisting subscription_status=active with stale limits here would
                # silently corrupt entitlements. Raise inside the atomic block so the
                # whole update rolls back and Stripe retries (self-heals a deploy/sync
                # race; alerts ops via the 5xx if the plan is genuinely missing).
                logger.critical("Billing plan not found during subscription update — not persisting stale limits")
                raise BillingRetryableError("Billing plan not found during subscription update") from e

        team.billing_plan_limits = billing_limits
        team.save()

    if subscription.status == "trialing" and subscription.trial_end:
        try:
            handle_trial_period(subscription, team)
        except BillingRetryableError:
            # Transient handle_trial_period failures (DB blip during the trial-expiry
            # downgrade, etc.) are already surfaced as BillingRetryableError by its
            # @handle_stripe_errors decorator — propagate so the event retries (5xx).
            raise
        except StripeError as e:
            # Defensive: handle_trial_period makes no Stripe calls today, so it cannot
            # raise a plain terminal StripeError — but if that ever changes, reclassify it
            # as retryable here rather than letting a trial-processing failure be
            # acknowledged with 200.
            raise BillingRetryableError(f"Trial-period processing failed: {e!s}") from e

    return billing_limits


def _send_subscription_notifications(team: Team, status: str, previous_status: Any) -> None:
    """Send appropriate notifications based on subscription status *transitions*."""
    if status == previous_status:
        return

    if status == "past_due":
        notify_team_owners(team, email_notifications.notify_payment_past_due)
        logger.warning("Payment past due notification sent")

    elif status == "active":
        notify_team_owners(team, email_notifications.notify_payment_succeeded)
        logger.info("Payment restored notification sent")

    elif status == "canceled":
        notify_team_owners(team, email_notifications.notify_subscription_cancelled)
        logger.info("Subscription cancelled notification sent")

    elif status in ["incomplete", "incomplete_expired"]:
        notify_team_owners(team, email_notifications.notify_payment_failed, None)
        logger.warning("Initial payment failed notification sent")


@handle_stripe_errors
def handle_subscription_deleted(subscription: Any, event: Any = None) -> None:
    """Handle subscription deletion events.

    Args:
        subscription: Stripe subscription object
        event: Optional Stripe event object for idempotency checking
    """
    try:
        team = Team.objects.get(billing_plan_limits__stripe_subscription_id=subscription.id)

        billing_limits = team.billing_plan_limits or {}

        webhook_id = generate_webhook_id(event, subscription, prefix="del")
        last_processed_id = billing_limits.get("last_processed_webhook_id")

        if last_processed_id == webhook_id:
            logger.info("Webhook already processed for deleted subscription, skipping")
            return

        _best_effort("subscription cache invalidation", invalidate_subscription_cache, subscription.id, team.key)

        cancel_at_period_end = billing_limits.get("cancel_at_period_end", False)
        scheduled_downgrade_plan = billing_limits.get("scheduled_downgrade_plan")

        if cancel_at_period_end and scheduled_downgrade_plan:
            logger.info("Processing scheduled downgrade")

            try:
                target_plan = BillingPlan.objects.get(key=scheduled_downgrade_plan)
            except BillingPlan.DoesNotExist:
                logger.error("Target plan not found for scheduled downgrade")
                with transaction.atomic():
                    team = Team.objects.select_for_update().get(pk=team.pk)
                    billing_limits = (team.billing_plan_limits or {}).copy()
                    billing_limits["subscription_status"] = "canceled"
                    billing_limits["last_updated"] = timezone.now().isoformat()
                    billing_limits.pop("scheduled_downgrade_plan", None)
                    billing_limits["cancel_at_period_end"] = False
                    billing_limits["last_processed_webhook_id"] = webhook_id
                    team.billing_plan_limits = billing_limits
                    team.save()
            else:
                counts = get_team_asset_counts(str(team.id))
                product_count = counts["products"]
                component_count = counts["components"]

                usage_exceeds_limits = False
                exceeded_resources: list[str] = []

                if target_plan.max_products is not None and product_count > target_plan.max_products:
                    usage_exceeds_limits = True
                    exceeded_resources.append(f"{product_count} products (limit: {target_plan.max_products})")

                if target_plan.max_components is not None and component_count > target_plan.max_components:
                    usage_exceeds_limits = True
                    exceeded_resources.append(f"{component_count} components (limit: {target_plan.max_components})")

                if usage_exceeds_limits:
                    with transaction.atomic():
                        team = Team.objects.select_for_update().get(pk=team.pk)
                        existing_limits: dict[str, Any] = (team.billing_plan_limits or {}).copy()
                        existing_limits.update(
                            {
                                "downgrade_exceeded": True,
                                "subscription_status": "canceled",
                                "payment_failed_at": timezone.now().isoformat(),
                                "last_updated": timezone.now().isoformat(),
                                "last_processed_webhook_id": webhook_id,
                            }
                        )
                        if "stripe_customer_id" not in existing_limits:
                            if hasattr(subscription, "customer"):
                                existing_limits["stripe_customer_id"] = subscription.customer

                        existing_limits.pop("scheduled_downgrade_plan", None)
                        existing_limits["cancel_at_period_end"] = False

                        team.billing_plan_limits = existing_limits
                        team.save()

                    logger.warning(f"Downgrade blocked due to exceeded limits: {', '.join(exceeded_resources)}")
                else:
                    with transaction.atomic():
                        team = Team.objects.select_for_update().get(pk=team.pk)
                        existing_limits = (team.billing_plan_limits or {}).copy()
                        existing_limits.update(
                            {
                                "max_products": target_plan.max_products,
                                "max_components": target_plan.max_components,
                                "subscription_status": "canceled",
                                "cancel_at_period_end": False,
                                "last_updated": timezone.now().isoformat(),
                                "last_processed_webhook_id": webhook_id,
                            }
                        )
                        if "stripe_customer_id" not in existing_limits:
                            if hasattr(subscription, "customer"):
                                existing_limits["stripe_customer_id"] = subscription.customer

                        existing_limits.pop("scheduled_downgrade_plan", None)

                        team.billing_plan = target_plan.key
                        team.billing_plan_limits = existing_limits
                        team.save()

                    if target_plan.key == BillingPlan.KEY_COMMUNITY:
                        handle_community_downgrade_visibility(team)

                    logger.info(f"Completed downgrade to {target_plan.key}")
        else:
            with transaction.atomic():
                team = Team.objects.select_for_update().get(pk=team.pk)
                billing_limits = (team.billing_plan_limits or {}).copy()
                billing_limits["subscription_status"] = "canceled"
                billing_limits["last_updated"] = timezone.now().isoformat()
                billing_limits["last_processed_webhook_id"] = webhook_id
                team.billing_plan_limits = billing_limits
                team.save()

        _best_effort(
            "subscription ended notification", notify_team_owners, team, email_notifications.notify_subscription_ended
        )
        logger.info("Subscription ended notification sent")

        from sbomify.apps.core.posthog_service import capture, group_identify

        workspace_key = team.key
        distinct_id = workspace_key or "system"
        capture(
            distinct_id,
            "billing:subscription_canceled",
            {"plan": team.billing_plan or ""},
            groups={"workspace": workspace_key} if workspace_key else None,
        )
        if workspace_key:
            group_identify(
                "workspace",
                workspace_key,
                {"billing_plan": team.billing_plan, "subscription_status": "canceled"},
            )

        logger.info("Subscription canceled")

    except Exception as e:
        _raise_classified_webhook_error(e)


@handle_stripe_errors
def handle_payment_failed(invoice: Any, event: Any = None) -> None:
    """Handle payment failure events.

    Args:
        invoice: Stripe invoice object
        event: Optional Stripe event object for idempotency checking
    """
    if not hasattr(invoice, "subscription") or not invoice.subscription:
        logger.error("No subscription found in invoice")
        return

    try:
        team = Team.objects.get(billing_plan_limits__stripe_subscription_id=invoice.subscription)
        billing_limits = team.billing_plan_limits or {}

        webhook_id = getattr(event, "id", None) if event else f"inv_fail_{invoice.id}_{invoice.created}"
        last_processed_id = billing_limits.get("last_processed_webhook_id")

        if last_processed_id == webhook_id:
            logger.info(f"Payment failed webhook already processed for invoice {invoice.id}, skipping")
            return

        with transaction.atomic():
            team = Team.objects.select_for_update().get(pk=team.pk)
            billing_limits = (team.billing_plan_limits or {}).copy()
            billing_limits["subscription_status"] = "past_due"
            billing_limits["last_updated"] = timezone.now().isoformat()
            # Keep the FIRST failure time so the grace period counts down. Stripe retries the
            # invoice, and resetting this to now() on every failed-payment event kept the grace
            # window from ever expiring. Guard on falsy (not just absent) so a None/"" doesn't
            # slip through, matching stripe_sync's handling.
            if not billing_limits.get("payment_failed_at"):
                billing_limits["payment_failed_at"] = timezone.now().isoformat()
            billing_limits["last_processed_webhook_id"] = webhook_id
            team.billing_plan_limits = billing_limits
            team.save()

        _best_effort("invoice cache invalidation", invalidate_subscription_cache, invoice.subscription, team.key)

        _best_effort(
            "payment failed notification",
            notify_team_owners,
            team,
            email_notifications.notify_payment_failed,
            invoice.id,
        )
        logger.warning(f"Payment failed notification sent (invoice {invoice.id})")

        from sbomify.apps.core.posthog_service import capture

        workspace_key = team.key
        distinct_id = workspace_key or "system"
        capture(
            distinct_id,
            "billing:payment_failed",
            {"invoice_id": invoice.id, "plan": team.billing_plan or ""},
            groups={"workspace": workspace_key} if workspace_key else None,
        )

        logger.warning("Payment failed")

    except Exception as e:
        _raise_classified_webhook_error(e)


@handle_stripe_errors
def handle_payment_succeeded(invoice: Any, event: Any = None) -> None:
    """Handle payment success events.

    Args:
        invoice: Stripe invoice object
        event: Optional Stripe event object for idempotency checking
    """
    if not hasattr(invoice, "subscription") or not invoice.subscription:
        logger.error("No subscription found in invoice")
        return

    try:
        team = Team.objects.get(billing_plan_limits__stripe_subscription_id=invoice.subscription)
        billing_limits = team.billing_plan_limits or {}

        webhook_id = getattr(event, "id", None) if event else f"inv_succ_{invoice.id}_{invoice.created}"
        last_processed_id = billing_limits.get("last_processed_webhook_id")

        if last_processed_id == webhook_id:
            logger.info(f"Payment succeeded webhook already processed for invoice {invoice.id}, skipping")
            return

        next_billing_date = None
        if invoice.subscription:
            try:
                subscription = stripe_client.get_subscription(invoice.subscription)
                if hasattr(subscription, "current_period_end") and subscription.current_period_end:
                    next_billing_date = datetime.datetime.fromtimestamp(
                        subscription.current_period_end, tz=datetime.timezone.utc
                    ).isoformat()
            except Exception as e:
                logger.warning(f"Failed to fetch subscription for next billing date: {e}")

        with transaction.atomic():
            team = Team.objects.select_for_update().get(pk=team.pk)
            billing_limits = (team.billing_plan_limits or {}).copy()
            billing_limits["subscription_status"] = "active"
            billing_limits["last_updated"] = timezone.now().isoformat()
            # Payment recovered — clear the failure marker so the grace window resets for any
            # future failure episode. The "keep first failure time" guard on the failed-payment
            # webhook would otherwise reuse this stale timestamp and treat the next failure as
            # already past grace.
            billing_limits.pop("payment_failed_at", None)
            billing_limits["last_payment_amount"] = invoice.amount_paid / 100.0 if invoice.amount_paid else 0.0
            billing_limits["last_payment_currency"] = invoice.currency
            billing_limits["last_processed_webhook_id"] = webhook_id

            if next_billing_date:
                billing_limits["next_billing_date"] = next_billing_date

            team.billing_plan_limits = billing_limits
            team.save()

        _best_effort("invoice cache invalidation", invalidate_subscription_cache, invoice.subscription, team.key)

        _best_effort(
            "payment succeeded notification", notify_team_owners, team, email_notifications.notify_payment_succeeded
        )
        logger.info("Payment successful notification sent")

        from sbomify.apps.core.posthog_service import capture

        amount = invoice.amount_paid / 100.0 if invoice.amount_paid else 0.0
        workspace_key = team.key
        distinct_id = workspace_key or "system"
        capture(
            distinct_id,
            "billing:payment_succeeded",
            {
                "amount": amount,
                "currency": invoice.currency or "usd",
                "invoice_id": invoice.id,
                "plan": team.billing_plan or "",
            },
            groups={"workspace": workspace_key} if workspace_key else None,
        )

    except Exception as e:
        _raise_classified_webhook_error(e)


def get_current_limits(team: Team) -> dict[str, Any]:
    """
    Get current billing limits for a team.

    Args:
        team: Team object

    Returns:
        Dictionary with current limits (max_products, max_components)
    """
    if not is_billing_enabled():
        return get_unlimited_plan_limits()

    if not team.billing_plan:
        return get_unlimited_plan_limits()

    try:
        plan = BillingPlan.objects.get(key=team.billing_plan)
        return {
            "max_products": plan.max_products,
            "max_components": plan.max_components,
            "max_users": plan.max_users,
            "subscription_status": team.billing_plan_limits.get("subscription_status", "active")
            if team.billing_plan_limits
            else "active",
        }
    except BillingPlan.DoesNotExist:
        return get_unlimited_plan_limits()


@handle_stripe_errors
def handle_checkout_completed(session: Any) -> None:
    """Handle checkout session completed events."""
    # Accept "paid" (normal checkout) and "no_payment_required" (trial with card collection)
    if session.payment_status not in {"paid", "no_payment_required"}:
        logger.error("Payment status was not valid: %s", session.payment_status)
        return

    team_key = session.metadata.get("team_key")
    if not team_key:
        logger.error("No team key found in session metadata")
        return

    try:
        team = Team.objects.get(key=team_key)

        # Idempotency: a redelivery of the same checkout session must short-circuit
        # BEFORE the outbound Stripe calls (get_subscription / cancel_subscription),
        # otherwise each retry re-issues them. Keyed on the session id since the view
        # dispatches this handler without an event object.
        if (team.billing_plan_limits or {}).get("last_processed_checkout_session") == session.id:
            logger.info("Checkout session %s already processed for team %s, skipping", session.id, team_key)
            return

        plan_key = session.metadata.get("plan_key", "business")
        plan = BillingPlan.objects.get(key=plan_key)

        subscription = stripe_client.get_subscription(session.subscription)

        existing_subscription_id = (team.billing_plan_limits or {}).get("stripe_subscription_id")

        if existing_subscription_id and existing_subscription_id != session.subscription:
            logger.info("Cancelling old subscription to prevent double billing")
            try:
                stripe_client.cancel_subscription(existing_subscription_id)
                logger.info("Successfully cancelled old subscription")
            except StripeError as e:
                # A failed cancel (often a transient Stripe outage) must NOT be
                # acknowledged: returning 200 strands both subscriptions active
                # (double billing) with no retry. Raise retryable so Stripe
                # re-delivers; a persistent failure exhausts retries and alerts.
                logger.critical(
                    "CRITICAL: Failed to cancel old subscription: %s. "
                    "Both subscriptions would be active — deferring via retry.",
                    e,
                )
                raise BillingRetryableError(
                    "Cannot complete checkout yet: failed to cancel existing subscription; "
                    "retrying to avoid leaving both subscriptions active."
                ) from e
            except Exception as e:
                logger.critical(
                    "CRITICAL: Unexpected error cancelling old subscription: %s. "
                    "Both subscriptions would be active — deferring via retry.",
                    e,
                )
                raise BillingRetryableError(
                    "Cannot complete checkout yet: unexpected error cancelling existing subscription; "
                    "retrying to avoid leaving both subscriptions active."
                ) from e

        with transaction.atomic():
            team = Team.objects.select_for_update().get(pk=team.pk)

            # Re-check under the row lock: the unlocked guard above closes the common
            # sequential-redelivery case, but two concurrent deliveries could both pass
            # it before either committed. The lock serializes them here.
            if (team.billing_plan_limits or {}).get("last_processed_checkout_session") == session.id:
                logger.info("Checkout session %s already processed (checked after lock), skipping", session.id)
                return

            team.billing_plan = plan.key
            team.has_selected_billing_plan = True
            billing_limits: dict[str, Any] = {
                "max_products": plan.max_products,
                "max_components": plan.max_components,
                "stripe_customer_id": session.customer,
                "stripe_subscription_id": session.subscription,
                "subscription_status": subscription.status,
                "last_updated": timezone.now().isoformat(),
                "last_payment_amount": session.amount_total / 100.0 if session.amount_total else 0.0,
                "last_payment_currency": session.currency,
                "last_processed_checkout_session": session.id,
            }

            if hasattr(subscription, "current_period_end") and subscription.current_period_end:
                next_billing_date = datetime.datetime.fromtimestamp(
                    subscription.current_period_end, tz=datetime.timezone.utc
                ).isoformat()
                billing_limits["next_billing_date"] = next_billing_date

            if subscription.status == "trialing":
                billing_limits.update({"is_trial": True, "trial_end": subscription.trial_end})

            team.billing_plan_limits = billing_limits
            team.save()

        if subscription.status == "trialing":
            # Runs after the idempotency marker is committed: a transient failure here
            # returns 5xx, but the redelivery short-circuits on the marker rather than
            # re-running this step. That is a deliberate trade-off — re-running would
            # risk a duplicate trial-ending email, since handle_trial_period is not
            # idempotent — and the trial markers/expiry downgrade are reconciled by the
            # subsequent customer.subscription.updated event and the trial-sync cron.
            handle_trial_period(subscription, team)

        logger.info("Successfully processed checkout session for team %s", team_key)

        from sbomify.apps.core.posthog_service import capture, group_identify

        amount = session.amount_total / 100.0 if session.amount_total else 0.0
        if team_key:
            capture(
                team_key,
                "billing:checkout_completed",
                {
                    "plan": plan.key,
                    "amount": amount,
                    "currency": session.currency or "usd",
                    "subscription_status": subscription.status,
                },
                groups={"workspace": team_key},
            )
            group_identify(
                "workspace", team_key, {"billing_plan": plan.key, "subscription_status": subscription.status}
            )

    except Exception as e:
        # Team.DoesNotExist -> terminal; a missing BillingPlan / unexpected failure -> retryable
        # (don't drop a paid checkout). See _raise_classified_webhook_error.
        _raise_classified_webhook_error(e)


@handle_stripe_errors
def handle_price_updated(price: Any, event: Any = None) -> None:
    """Handle price update/created events from Stripe.

    When a price is updated or created in Stripe, sync it to the corresponding BillingPlan.
    Also handles cases where plans don't have Stripe IDs yet by finding matching plans.

    Args:
        price: Stripe price object
        event: Optional Stripe event object for idempotency checking
    """
    from .stripe_sync import sync_plan_prices_from_stripe

    try:
        price_id = price.id if hasattr(price, "id") else price.get("id")
        price_obj = price if hasattr(price, "product") else None

        plan = BillingPlan.objects.filter(
            models.Q(stripe_price_monthly_id=price_id) | models.Q(stripe_price_annual_id=price_id)
        ).first()

        if not plan and price_obj:
            try:
                product_id = (
                    price_obj.product
                    if isinstance(price_obj.product, str)
                    else price_obj.product.id
                    if hasattr(price_obj.product, "id")
                    else None
                )
                if product_id:
                    plan = BillingPlan.objects.filter(stripe_product_id=product_id).first()

                    if not plan:
                        try:
                            product = stripe_client.get_product(product_id)
                            if product and product.name:
                                plan = BillingPlan.objects.filter(name__iexact=product.name).first()
                                if plan:
                                    logger.info(f"Matched plan {plan.key} by product name '{product.name}'")
                        except Exception as e:
                            logger.debug(f"Error fetching product for name matching: {e}")

            except Exception as e:
                logger.debug(f"Error trying to find plan by product: {e}")

        if not plan:
            logger.debug(
                f"Price {price_id} updated but no matching plan found. "
                "This is normal for prices not yet associated with plans."
            )
            return

        logger.info(f"Price {price_id} updated, syncing plan {plan.key}")

        results = sync_plan_prices_from_stripe(plan_key=plan.key)

        if results["synced"] > 0:
            logger.info(f"Successfully synced prices for plan {plan.key} after price update")
        elif results["errors"]:
            logger.warning(f"Errors syncing prices for plan {plan.key} after price update: {results['errors']}")

    except Exception as e:
        logger.error("Error processing price update: %s", str(e), exc_info=True)
        raise StripeError(f"Error processing price update: {e!s}")
