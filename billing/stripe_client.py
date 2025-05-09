"""
Stripe client wrapper for handling Stripe operations.
"""

import logging
from functools import wraps

import stripe
from django.conf import settings

logger = logging.getLogger(__name__)


class StripeClient:
    """Wrapper for Stripe operations with proper error handling and caching."""

    def __init__(self, api_key=None):
        """Initialize Stripe client with API key."""
        self.api_key = api_key or settings.STRIPE_SECRET_KEY
        self.stripe = stripe
        self.stripe.api_key = self.api_key

    @staticmethod
    def _handle_stripe_error(func):
        """Decorator to handle Stripe errors consistently."""

        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except stripe.error.CardError as e:
                logger.error(f"Card error: {str(e)}")
                raise StripeError(f"Card error: {e.user_message}")
            except stripe.error.RateLimitError as e:
                logger.error(f"Rate limit error: {str(e)}")
                raise StripeError("Too many requests made to Stripe API")
            except stripe.error.InvalidRequestError as e:
                logger.error(f"Invalid request error: {str(e)}")
                raise StripeError(f"Invalid request: {str(e)}")
            except stripe.error.AuthenticationError as e:
                logger.error(f"Authentication error: {str(e)}")
                raise StripeError("Authentication with Stripe failed")
            except stripe.error.APIConnectionError as e:
                logger.error(f"API connection error: {str(e)}")
                raise StripeError("Could not connect to Stripe API")
            except stripe.error.StripeError as e:
                logger.error(f"Stripe error: {str(e)}")
                raise StripeError(f"Stripe error: {str(e)}")
            except Exception as e:
                logger.exception(f"Unexpected error: {str(e)}")
                raise StripeError(f"Unexpected error: {str(e)}")

        return wrapper

    @_handle_stripe_error
    def get_customer(self, customer_id):
        """Retrieve a customer from Stripe."""
        return self.stripe.Customer.retrieve(customer_id)

    @_handle_stripe_error
    def create_customer(self, email, name, metadata=None):
        """Create a new customer in Stripe."""
        return self.stripe.Customer.create(email=email, name=name, metadata=metadata or {})

    @_handle_stripe_error
    def update_customer(self, customer_id, **kwargs):
        """Update a customer in Stripe."""
        return self.stripe.Customer.modify(customer_id, **kwargs)

    @_handle_stripe_error
    def create_subscription(self, customer_id, price_id, trial_days=None, metadata=None):
        """Create a new subscription."""
        subscription_data = {"customer": customer_id, "items": [{"price": price_id}], "metadata": metadata or {}}

        if trial_days:
            subscription_data["trial_period_days"] = trial_days

        return self.stripe.Subscription.create(**subscription_data)

    @_handle_stripe_error
    def update_subscription(self, subscription_id, **kwargs):
        """Update a subscription."""
        return self.stripe.Subscription.modify(subscription_id, **kwargs)

    @_handle_stripe_error
    def cancel_subscription(self, subscription_id, prorate=True):
        """Cancel a subscription."""
        return self.stripe.Subscription.delete(subscription_id, prorate=prorate)

    @_handle_stripe_error
    def get_subscription(self, subscription_id):
        """Retrieve a subscription."""
        return self.stripe.Subscription.retrieve(subscription_id, expand=["latest_invoice.payment_intent"])

    @_handle_stripe_error
    def create_checkout_session(self, customer_id, price_id, success_url, cancel_url, metadata=None):
        """Create a checkout session."""
        return self.stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata or {},
        )

    @_handle_stripe_error
    def get_checkout_session(self, session_id):
        """Retrieve a checkout session."""
        return self.stripe.checkout.Session.retrieve(session_id)

    @_handle_stripe_error
    def construct_webhook_event(self, payload, sig_header):
        """Construct a webhook event from payload and signature."""
        return self.stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)


class StripeError(Exception):
    """Base class for Stripe-related errors."""

    pass
