"""
Stripe client wrapper for handling Stripe operations.
"""

import logging
from functools import wraps

import stripe
from django.conf import settings

from .utils import STRIPE_API_LIMIT

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
                logger.error(f"Unexpected error: {str(e)}")
                raise StripeError(f"Unexpected error: {str(e)}")

        return wrapper

    @_handle_stripe_error
    def get_customer(self, customer_id):
        """Retrieve a customer from Stripe."""
        return self.stripe.Customer.retrieve(customer_id)

    @_handle_stripe_error
    def create_customer(self, email, name, metadata=None, id=None):
        """Create a new customer in Stripe."""
        kwargs = {"email": email, "name": name, "metadata": metadata or {}}
        if id is not None:
            kwargs["id"] = id
        return self.stripe.Customer.create(**kwargs)

    @_handle_stripe_error
    def update_customer(self, customer_id, **kwargs):
        """Update a customer in Stripe."""
        return self.stripe.Customer.modify(customer_id, **kwargs)

    @_handle_stripe_error
    def create_subscription(self, customer_id, price_id, trial_days=None, metadata=None):
        """Create a new subscription."""
        # Ensure we have the customer metadata
        customer = self.get_customer(customer_id)

        # Validate customer metadata
        if not customer.metadata or "team_key" not in customer.metadata:
            raise ValueError("Customer must have team_key in metadata")

        # Merge metadata, preferring provided metadata over customer metadata
        if not metadata:
            metadata = customer.metadata.copy()
        else:
            metadata = {**customer.metadata, **metadata}

        # Ensure team_key is present
        if "team_key" not in metadata:
            metadata["team_key"] = customer.metadata["team_key"]

        subscription_data = {"customer": customer_id, "items": [{"price": price_id}], "metadata": metadata}

        if trial_days:
            subscription_data["trial_period_days"] = trial_days

        subscription = self.stripe.Subscription.create(**subscription_data)

        # Double-check metadata was set
        if not subscription.metadata or "team_key" not in subscription.metadata:
            subscription = self.stripe.Subscription.modify(subscription.id, metadata=metadata)

        return subscription

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
        return self.stripe.Subscription.retrieve(
            subscription_id, expand=["latest_invoice.payment_intent", "items.data.price"]
        )

    @_handle_stripe_error
    def create_checkout_session(self, customer_id, price_id, success_url, cancel_url, metadata=None):
        """Create a checkout session. Stripe handles promo codes via allow_promotion_codes."""
        session_data = {
            "customer": customer_id,
            "payment_method_types": ["card"],
            "line_items": [
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": metadata or {},
        }

        return self.stripe.checkout.Session.create(**session_data)

    @_handle_stripe_error
    def get_checkout_session(self, session_id):
        """Retrieve a checkout session."""
        return self.stripe.checkout.Session.retrieve(session_id)

    @_handle_stripe_error
    def create_billing_portal_session(self, customer_id, return_url, flow_data=None):
        """
        Create a billing portal session for customer to manage subscription.

        Args:
            customer_id: Stripe Customer ID
            return_url: URL to redirect after portal
            flow_data: Optional dict to configure portal flow (e.g. subscription_update)
        """
        params = {
            "customer": customer_id,
            "return_url": return_url,
        }
        if flow_data:
            params["flow_data"] = flow_data

        return self.stripe.billing_portal.Session.create(**params)

    @_handle_stripe_error
    def get_price(self, price_id):
        """Retrieve a price object from Stripe."""
        return self.stripe.Price.retrieve(price_id)

    @_handle_stripe_error
    def get_invoice(self, invoice_id):
        """Retrieve an invoice from Stripe."""
        return self.stripe.Invoice.retrieve(invoice_id)

    @_handle_stripe_error
    def construct_webhook_event(self, payload, sig_header, webhook_secret=None):
        """Construct a webhook event from payload and signature."""
        secret = webhook_secret or settings.STRIPE_WEBHOOK_SECRET
        return self.stripe.Webhook.construct_event(payload, sig_header, secret)

    @_handle_stripe_error
    def get_product_with_prices(self, product_id):
        """Retrieve a product with all its prices."""
        product = self.stripe.Product.retrieve(product_id)
        prices = self.stripe.Price.list(product=product_id, active=True, limit=STRIPE_API_LIMIT)
        return product, prices.data

    @_handle_stripe_error
    def get_all_products_with_prices(self):
        """Retrieve all active products with their prices."""
        products = self.stripe.Product.list(active=True, limit=STRIPE_API_LIMIT)
        result = []

        for product in products.data:
            prices = self.stripe.Price.list(product=product.id, active=True, limit=STRIPE_API_LIMIT)
            result.append({"product": product, "prices": prices.data})

        return result


class StripeError(Exception):
    """Base class for Stripe-related errors."""

    pass
