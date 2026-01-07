"""
Stripe webhook handler with proper security and idempotency.
"""

import logging
import time

from django.core.cache import cache
from django.http import HttpResponse, HttpResponseForbidden

# Try to import HttpResponseTooManyRequests, fallback if not available
try:
    from django.http import HttpResponseTooManyRequests
except ImportError:
    # Create a custom response class for older Django versions
    class HttpResponseTooManyRequests(HttpResponse):
        status_code = 429


from .stripe_client import StripeClient, StripeError

logger = logging.getLogger(__name__)


class WebhookHandler:
    """Handler for Stripe webhooks with security and idempotency."""

    def __init__(self, stripe_client=None):
        """Initialize webhook handler."""
        self.stripe_client = stripe_client or StripeClient()
        self.rate_limit_window = 60  # 1 minute
        self.max_requests = 100  # Max requests per minute

    def _rate_limit_check(self, request):
        """Check if request is within rate limits."""
        client_ip = request.META.get("REMOTE_ADDR")
        key = f"webhook_rate_limit_{client_ip}"

        # Get current requests count
        requests = cache.get(key, [])
        now = time.time()

        # Remove old requests
        requests = [req_time for req_time in requests if now - req_time < self.rate_limit_window]

        # Check if we're over the limit
        if len(requests) >= self.max_requests:
            return False

        # Add current request
        requests.append(now)
        cache.set(key, requests, self.rate_limit_window)
        return True

    def _check_idempotency(self, event_id):
        """Check if event has already been processed."""
        if not event_id:
            return False

        key = f"webhook_event_{event_id}"
        if cache.get(key):
            return True

        cache.set(key, True, timeout=86400)  # 24 hours
        return False

    def _verify_webhook(self, request):
        """Verify webhook signature and construct event."""
        sig_header = request.headers.get("Stripe-Signature")
        if not sig_header:
            logger.error("No Stripe signature found in request headers")
            return None

        try:
            return self.stripe_client.construct_webhook_event(request.body, sig_header)
        except Exception as e:
            logger.error(f"Error verifying webhook: {str(e)}")
            return None

    def handle_webhook(self, request):
        """Handle incoming webhook request."""
        # Check rate limit
        if not self._rate_limit_check(request):
            return HttpResponseTooManyRequests("Rate limit exceeded")

        # Verify webhook
        event = self._verify_webhook(request)
        if not event:
            return HttpResponseForbidden("Invalid webhook signature")

        # Check idempotency
        event_id = request.headers.get("Stripe-Event-Id")
        if self._check_idempotency(event_id):
            return HttpResponse(status=200)  # Already processed

        # Check webhook version
        if request.headers.get("Stripe-Event-Version") != "2020-08-27":
            logger.warning(f"Unsupported webhook version: {request.headers.get('Stripe-Event-Version')}")

        try:
            # Handle the event
            if event.type == "checkout.session.completed":
                self._handle_checkout_completed(event.data.object)
            elif event.type == "customer.subscription.updated":
                self._handle_subscription_updated(event.data.object)
            elif event.type == "customer.subscription.deleted":
                self._handle_subscription_deleted(event.data.object)
            elif event.type == "invoice.payment_failed":
                self._handle_payment_failed(event.data.object)
            elif event.type == "invoice.payment_succeeded":
                self._handle_payment_succeeded(event.data.object)
            elif event.type in ["price.updated", "price.created"]:
                self._handle_price_updated(event.data.object)
            else:
                logger.info(f"Unhandled event type: {event.type}")

            return HttpResponse(status=200)

        except StripeError as e:
            logger.error(f"Error processing webhook: {str(e)}")
            return HttpResponse(status=400)
        except Exception as e:
            logger.error(f"Unexpected error processing webhook: {str(e)}")
            return HttpResponse(status=500)

    def _handle_checkout_completed(self, session):
        """Handle checkout completed event."""
        from .billing_processing import handle_checkout_completed

        handle_checkout_completed(session)

    def _handle_subscription_updated(self, subscription):
        """Handle subscription updated event."""
        from .billing_processing import handle_subscription_updated

        handle_subscription_updated(subscription)

    def _handle_subscription_deleted(self, subscription):
        """Handle subscription deleted event."""
        from .billing_processing import handle_subscription_deleted

        handle_subscription_deleted(subscription)

    def _handle_payment_failed(self, invoice):
        """Handle payment failed event."""
        from .billing_processing import handle_payment_failed

        handle_payment_failed(invoice)

    def _handle_payment_succeeded(self, invoice):
        """Handle payment succeeded event."""
        from .billing_processing import handle_payment_succeeded

        handle_payment_succeeded(invoice)

    def _handle_price_updated(self, price):
        """Handle price updated event."""
        from .billing_processing import handle_price_updated

        handle_price_updated(price)
