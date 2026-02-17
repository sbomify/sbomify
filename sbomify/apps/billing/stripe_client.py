"""
Stripe client wrapper for handling Stripe operations.
"""

import threading
from functools import wraps

import stripe
from django.conf import settings

from sbomify.logging import getLogger

from .utils import STRIPE_API_LIMIT

logger = getLogger(__name__)


class StripeError(Exception):
    """Base class for Stripe-related errors."""

    pass


def handle_stripe_errors(func):
    """Decorator to handle Stripe errors consistently.

    Catches all Stripe-specific errors and re-raises as StripeError.
    Also catches unexpected exceptions to prevent unhandled crashes in
    billing code paths.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except StripeError:
            raise
        except stripe.error.CardError as e:
            logger.error("Card error: code=%s, param=%s", e.code, e.param)
            raise StripeError(f"Card error: {e.user_message}")
        except stripe.error.RateLimitError as e:
            logger.error("Rate limit error: %s", e.code)
            raise StripeError("Too many requests made to Stripe API")
        except stripe.error.InvalidRequestError as e:
            logger.error("Invalid Stripe request: param=%s, message=%s", e.param, str(e))
            raise StripeError("Invalid request to payment provider.")
        except stripe.error.AuthenticationError:
            logger.error("Stripe authentication error")
            raise StripeError("Authentication with payment provider failed.")
        except stripe.error.APIConnectionError:
            logger.error("Stripe API connection error")
            raise StripeError("Could not connect to payment provider.")
        except stripe.error.StripeError as e:
            logger.error("Stripe error: code=%s, message=%s", e.code, str(e))
            raise StripeError("A payment processing error occurred.")
        except Exception as e:
            logger.error("Unexpected error in Stripe operation: %s", type(e).__name__, exc_info=True)
            raise StripeError("An unexpected error occurred.") from e

    return wrapper


class StripeClient:
    """Wrapper for Stripe operations with proper error handling.

    All API calls pass api_key explicitly to avoid mutating global stripe
    module state, making this safe for concurrent request handling.
    """

    def __init__(self, api_key=None):
        """Initialize Stripe client with API key."""
        self._api_key = api_key or settings.STRIPE_SECRET_KEY

    @handle_stripe_errors
    def get_customer(self, customer_id):
        """Retrieve a customer from Stripe."""
        return stripe.Customer.retrieve(customer_id, api_key=self._api_key)

    @handle_stripe_errors
    def create_customer(self, email, name, metadata=None, id=None):
        """Create a new customer in Stripe."""
        kwargs = {"email": email, "name": name, "metadata": metadata or {}, "api_key": self._api_key}
        if id is not None:
            kwargs["id"] = id
        return stripe.Customer.create(**kwargs)

    @handle_stripe_errors
    def update_customer(self, customer_id, **kwargs):
        """Update a customer in Stripe."""
        return stripe.Customer.modify(customer_id, api_key=self._api_key, **kwargs)

    @handle_stripe_errors
    def create_subscription(self, customer_id, price_id, trial_days=None, metadata=None):
        """Create a new subscription."""
        customer = self.get_customer(customer_id)

        if not customer.metadata or "team_key" not in customer.metadata:
            raise ValueError("Customer must have team_key in metadata")

        if not metadata:
            metadata = customer.metadata.copy()
        else:
            metadata = {**customer.metadata, **metadata}

        if "team_key" not in metadata:
            metadata["team_key"] = customer.metadata["team_key"]

        subscription_data = {
            "customer": customer_id,
            "items": [{"price": price_id}],
            "metadata": metadata,
            "api_key": self._api_key,
        }

        if trial_days:
            subscription_data["trial_period_days"] = trial_days

        subscription = stripe.Subscription.create(**subscription_data)

        if not subscription.metadata or "team_key" not in subscription.metadata:
            subscription = stripe.Subscription.modify(subscription.id, metadata=metadata, api_key=self._api_key)

        return subscription

    @handle_stripe_errors
    def cancel_subscription(self, subscription_id, prorate=True):
        """Cancel a subscription."""
        return stripe.Subscription.delete(subscription_id, prorate=prorate, api_key=self._api_key)

    @handle_stripe_errors
    def get_subscription(self, subscription_id):
        """Retrieve a subscription."""
        return stripe.Subscription.retrieve(
            subscription_id,
            expand=["latest_invoice.payment_intent", "items.data.price"],
            api_key=self._api_key,
        )

    @handle_stripe_errors
    def create_checkout_session(self, customer_id, price_id, success_url, cancel_url, metadata=None):
        """Create a checkout session. Stripe handles promo codes via allow_promotion_codes."""
        session_data = {
            "customer": customer_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": metadata or {},
            "api_key": self._api_key,
        }

        return stripe.checkout.Session.create(**session_data)

    @handle_stripe_errors
    def get_checkout_session(self, session_id):
        """Retrieve a checkout session."""
        return stripe.checkout.Session.retrieve(session_id, api_key=self._api_key)

    @handle_stripe_errors
    def create_billing_portal_session(self, customer_id, return_url, flow_data=None):
        """Create a billing portal session for customer to manage subscription."""
        params = {
            "customer": customer_id,
            "return_url": return_url,
            "api_key": self._api_key,
        }
        if flow_data:
            params["flow_data"] = flow_data

        return stripe.billing_portal.Session.create(**params)

    @handle_stripe_errors
    def get_price(self, price_id):
        """Retrieve a price object from Stripe."""
        return stripe.Price.retrieve(price_id, api_key=self._api_key)

    @handle_stripe_errors
    def get_invoice(self, invoice_id):
        """Retrieve an invoice from Stripe."""
        return stripe.Invoice.retrieve(invoice_id, api_key=self._api_key)

    @handle_stripe_errors
    def construct_webhook_event(self, payload, sig_header, webhook_secret=None):
        """Construct a webhook event from payload and signature."""
        secret = webhook_secret or settings.STRIPE_WEBHOOK_SECRET
        return stripe.Webhook.construct_event(payload, sig_header, secret)

    @handle_stripe_errors
    def get_product_with_prices(self, product_id):
        """Retrieve a product with all its prices."""
        product = stripe.Product.retrieve(product_id, api_key=self._api_key)
        prices = stripe.Price.list(product=product_id, active=True, limit=STRIPE_API_LIMIT, api_key=self._api_key)
        return product, prices.data

    @handle_stripe_errors
    def get_all_products_with_prices(self):
        """Retrieve all active products with their prices."""
        products = stripe.Product.list(active=True, limit=STRIPE_API_LIMIT, api_key=self._api_key)
        result = []

        for product in products.data:
            prices = stripe.Price.list(product=product.id, active=True, limit=STRIPE_API_LIMIT, api_key=self._api_key)
            result.append({"product": product, "prices": prices.data})

        return result

    @handle_stripe_errors
    def list_subscriptions(self, customer_id, limit=1):
        """List subscriptions for a customer."""
        return stripe.Subscription.list(customer=customer_id, limit=limit, api_key=self._api_key)

    @handle_stripe_errors
    def list_invoices(self, **kwargs):
        """List invoices with optional filters."""
        return stripe.Invoice.list(api_key=self._api_key, **kwargs)

    @handle_stripe_errors
    def get_product(self, product_id):
        """Retrieve a product from Stripe."""
        return stripe.Product.retrieve(product_id, api_key=self._api_key)

    @handle_stripe_errors
    def list_products(self, **kwargs):
        """List products with optional filters."""
        return stripe.Product.list(api_key=self._api_key, **kwargs)

    @handle_stripe_errors
    def list_prices(self, **kwargs):
        """List prices with optional filters."""
        return stripe.Price.list(api_key=self._api_key, **kwargs)

    @handle_stripe_errors
    def modify_subscription(self, subscription_id, **kwargs):
        """Modify a subscription (e.g. cancel_at_period_end)."""
        return stripe.Subscription.modify(subscription_id, api_key=self._api_key, **kwargs)

    @handle_stripe_errors
    def create_checkout_session_raw(self, session_data: dict):
        """Create a checkout session from a pre-built session data dict."""
        return stripe.checkout.Session.create(**session_data, api_key=self._api_key)


_lock = threading.Lock()
_default_client: StripeClient | None = None


def get_stripe_client() -> StripeClient:
    """Return a shared StripeClient singleton (thread-safe)."""
    global _default_client
    if _default_client is None:
        with _lock:
            if _default_client is None:
                _default_client = StripeClient()
    return _default_client


def _reset_default_client() -> None:
    """Reset the singleton for test isolation."""
    global _default_client
    _default_client = None
