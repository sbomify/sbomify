"""Extended tests for billing views covering edge cases and missing scenarios."""

import json
from unittest.mock import MagicMock, patch

import pytest
import stripe
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
from django.test import Client, RequestFactory
from django.urls import reverse

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.tests.fixtures import (  # noqa: F401
    business_plan,
    community_plan,
    enterprise_plan,
    sample_user,
)
from sbomify.apps.core.tests.shared_fixtures import team_with_business_plan  # noqa: F401
from sbomify.apps.teams.models import Member, Team

User = get_user_model()
pytestmark = pytest.mark.django_db


class TestBillingReturnView:
    """Test cases for billing_return view."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.client = Client()

    @patch("stripe.checkout.Session.retrieve")
    @patch("stripe.Subscription.retrieve")
    @patch("stripe.Customer.retrieve")
    def test_billing_return_success(
        self,
        mock_customer_retrieve,
        mock_subscription_retrieve,
        mock_session_retrieve,
        sample_user: AbstractBaseUser,  # noqa: F811
        team_with_business_plan: Team,  # noqa: F811
        business_plan: BillingPlan,  # noqa: F811
    ):
        """Test successful billing return from Stripe."""
        # Mock session data
        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_session.subscription = "sub_123"
        mock_session.customer = "cus_123"
        mock_session.metadata = {"team_key": team_with_business_plan.key}
        mock_session_retrieve.return_value = mock_session

        # Mock subscription data
        mock_subscription = MagicMock()
        mock_subscription.id = "sub_123"
        mock_subscription.status = "active"
        mock_subscription.get.return_value = {"data": [{"plan": {"interval": "month"}}]}
        mock_subscription_retrieve.return_value = mock_subscription

        # Mock customer data
        mock_customer = MagicMock()
        mock_customer.id = "cus_123"
        mock_customer_retrieve.return_value = mock_customer

        self.client.force_login(sample_user)

        response = self.client.get(
            reverse("billing:billing_return") + "?session_id=cs_test123"
        )

        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")

        # Verify team billing information was updated
        team_with_business_plan.refresh_from_db()
        assert team_with_business_plan.billing_plan == "business"
        assert "stripe_customer_id" in team_with_business_plan.billing_plan_limits
        assert "stripe_subscription_id" in team_with_business_plan.billing_plan_limits

    @patch("stripe.checkout.Session.retrieve")
    def test_billing_return_payment_not_paid(
        self, mock_session_retrieve, sample_user: AbstractBaseUser  # noqa: F811
    ):
        """Test billing return with non-paid payment status."""
        mock_session = MagicMock()
        mock_session.payment_status = "failed"
        mock_session_retrieve.return_value = mock_session

        self.client.force_login(sample_user)

        response = self.client.get(
            reverse("billing:billing_return") + "?session_id=cs_test123"
        )

        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")

    @patch("stripe.checkout.Session.retrieve")
    def test_billing_return_no_session_id(self, mock_session_retrieve, sample_user: AbstractBaseUser):  # noqa: F811
        """Test billing return without session ID."""
        self.client.force_login(sample_user)

        response = self.client.get(reverse("billing:billing_return"))

        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")
        mock_session_retrieve.assert_not_called()

    @patch("stripe.checkout.Session.retrieve")
    def test_billing_return_stripe_error(
        self, mock_session_retrieve, sample_user: AbstractBaseUser  # noqa: F811
    ):
        """Test billing return with Stripe error."""
        mock_session_retrieve.side_effect = stripe.error.StripeError("API error")

        self.client.force_login(sample_user)

        response = self.client.get(
            reverse("billing:billing_return") + "?session_id=cs_test123"
        )

        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")

    @patch("stripe.checkout.Session.retrieve")
    def test_billing_return_no_team_key_in_metadata(
        self, mock_session_retrieve, sample_user: AbstractBaseUser  # noqa: F811
    ):
        """Test billing return with missing team key in metadata."""
        mock_session = MagicMock()
        mock_session.payment_status = "paid"
        mock_session.metadata = {}  # No team_key
        mock_session_retrieve.return_value = mock_session

        self.client.force_login(sample_user)

        response = self.client.get(
            reverse("billing:billing_return") + "?session_id=cs_test123"
        )

        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")

    def test_billing_return_requires_login(self):
        """Test billing return requires authentication."""
        response = self.client.get(
            reverse("billing:billing_return") + "?session_id=cs_test123"
        )

        assert response.status_code == 302
        assert response.status_code == 302
        assert "login" in response.url


class TestCheckoutViews:
    """Test cases for checkout success/cancel views."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.client = Client()

    def test_checkout_success_view(self, sample_user: AbstractBaseUser):  # noqa: F811
        """Test checkout success view."""
        self.client.force_login(sample_user)

        response = self.client.get(reverse("billing:checkout_success"))

        assert response.status_code == 200
        assert "billing/checkout_success.html.j2" in [t.name for t in response.templates]

    def test_checkout_cancel_view(self, sample_user: AbstractBaseUser):  # noqa: F811
        """Test checkout cancel view."""
        self.client.force_login(sample_user)

        response = self.client.get(reverse("billing:checkout_cancel"))

        assert response.status_code == 200
        assert "billing/checkout_cancel.html.j2" in [t.name for t in response.templates]

    def test_checkout_success_accessible_without_login(self):
        """Test checkout success is accessible without authentication (for Stripe callbacks)."""
        response = self.client.get(reverse("billing:checkout_success"))
        assert response.status_code == 200

    def test_checkout_cancel_accessible_without_login(self):
        """Test checkout cancel is accessible without authentication (for Stripe callbacks)."""
        response = self.client.get(reverse("billing:checkout_cancel"))
        assert response.status_code == 200


class TestBillingRedirectEdgeCases:
    """Test edge cases for billing_redirect view."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.client = Client()

    def test_billing_redirect_no_session_data(
        self, sample_user: AbstractBaseUser, team_with_business_plan: Team  # noqa: F811
    ):
        """Test billing redirect without session data."""
        self.client.force_login(sample_user)

        response = self.client.get(
            reverse("billing:billing_redirect", kwargs={"team_key": team_with_business_plan.key})
        )

        assert response.status_code == 302
        assert response.url == reverse("billing:select_plan", kwargs={"team_key": team_with_business_plan.key})

    def test_billing_redirect_non_owner(
        self, team_with_business_plan: Team  # noqa: F811
    ):
        """Test billing redirect with non-owner user."""
        user = User.objects.create_user(
            username="nonowner", email="nonowner@example.com", password="testpass123"
        )
        Member.objects.create(team=team_with_business_plan, user=user, role="member")

        self.client.force_login(user)

        response = self.client.get(
            reverse("billing:billing_redirect", kwargs={"team_key": team_with_business_plan.key})
        )

        assert response.status_code == 302
        assert response.url == reverse("core:dashboard")

        messages = list(get_messages(response.wsgi_request))
        assert any("Only team owners can change billing plans" in str(m) for m in messages)

    @patch("stripe.Customer.retrieve")
    @patch("stripe.Customer.create")
    @patch("stripe.checkout.Session.create")
    def test_billing_redirect_create_new_customer(
        self,
        mock_session_create,
        mock_customer_create,
        mock_customer_retrieve,
        sample_user: AbstractBaseUser,  # noqa: F811
        team_with_business_plan: Team,  # noqa: F811
        business_plan: BillingPlan,  # noqa: F811
    ):
        """Test billing redirect creating new customer."""
        # Mock customer doesn't exist
        mock_customer_retrieve.side_effect = stripe.error.InvalidRequestError(
            message="No such customer", param="id"
        )

        # Mock customer creation
        mock_customer = MagicMock()
        mock_customer.id = f"c_{team_with_business_plan.key}"
        mock_customer_create.return_value = mock_customer

        # Mock session creation
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/test"
        mock_session_create.return_value = mock_session

        # Set up session data
        session = self.client.session
        session["selected_plan"] = {
            "key": "business",
            "billing_period": "monthly",
            "limits": {"max_products": 10, "max_projects": 20, "max_components": 100},
        }
        session.save()

        self.client.force_login(sample_user)

        response = self.client.get(
            reverse("billing:billing_redirect", kwargs={"team_key": team_with_business_plan.key})
        )

        assert response.status_code == 302
        # Verify URL starts with expected Stripe checkout domain for security
        from urllib.parse import urlparse
        parsed_url = urlparse(response.url)
        assert parsed_url.netloc == "checkout.stripe.com"

        mock_customer_create.assert_called_once_with(
            id=f"c_{team_with_business_plan.key}",
            email=sample_user.email,
            name=team_with_business_plan.name,
            metadata={"team_key": team_with_business_plan.key},
        )

    @patch("stripe.Customer.retrieve")
    @patch("stripe.checkout.Session.create")
    def test_billing_redirect_annual_billing(
        self,
        mock_session_create,
        mock_customer_retrieve,
        sample_user: AbstractBaseUser,  # noqa: F811
        team_with_business_plan: Team,  # noqa: F811
        business_plan: BillingPlan,  # noqa: F811
    ):
        """Test billing redirect with annual billing period."""
        # Mock existing customer
        mock_customer = MagicMock()
        mock_customer.id = f"c_{team_with_business_plan.key}"
        mock_customer_retrieve.return_value = mock_customer

        # Mock session creation
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/test"
        mock_session_create.return_value = mock_session

        # Set up session data with annual billing
        session = self.client.session
        session["selected_plan"] = {
            "key": "business",
            "billing_period": "annual",
            "limits": {"max_products": 10, "max_projects": 20, "max_components": 100},
        }
        session.save()

        self.client.force_login(sample_user)

        response = self.client.get(
            reverse("billing:billing_redirect", kwargs={"team_key": team_with_business_plan.key})
        )

        assert response.status_code == 302
        # Verify URL starts with expected Stripe checkout domain for security
        from urllib.parse import urlparse
        parsed_url = urlparse(response.url)
        assert parsed_url.netloc == "checkout.stripe.com"

        # Verify that annual price ID was used
        call_args = mock_session_create.call_args[1]
        assert call_args["line_items"][0]["price"] == business_plan.stripe_price_annual_id

    def test_billing_redirect_missing_price_id(
        self, sample_user: AbstractBaseUser, team_with_business_plan: Team  # noqa: F811
    ):
        """Test billing redirect with missing price ID."""
        # Create plan without price IDs
        BillingPlan.objects.create(
            key="test_plan", name="Test Plan", stripe_price_monthly_id=None, stripe_price_annual_id=None
        )

        # Set up session data
        session = self.client.session
        session["selected_plan"] = {
            "key": "test_plan",
            "billing_period": "monthly",
            "limits": {},
        }
        session.save()

        self.client.force_login(sample_user)

        # Mock the actual Stripe calls to avoid real API calls
        with patch("stripe.Customer.retrieve") as mock_retrieve, \
             patch("stripe.checkout.Session.create") as mock_session_create:

            mock_retrieve.return_value = MagicMock(id="cus_123")
            mock_session_create.return_value = MagicMock(url="https://checkout.stripe.com/test")

            with pytest.raises(ValueError) as exc_info:
                self.client.get(
                    reverse("billing:billing_redirect", kwargs={"team_key": team_with_business_plan.key})
                )

            assert "No price ID found" in str(exc_info.value)


class TestEnterpriseContactView:
    """Test cases for enterprise contact functionality."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.client = Client()

    def test_select_enterprise_plan(
        self,
        sample_user: AbstractBaseUser,  # noqa: F811
        team_with_business_plan: Team,  # noqa: F811
        enterprise_plan: BillingPlan,  # noqa: F811
    ):
        """Test selecting enterprise plan shows contact page."""
        self.client.force_login(sample_user)

        response = self.client.post(
            reverse("billing:select_plan", kwargs={"team_key": team_with_business_plan.key}),
            {"plan": "enterprise"}
        )

        assert response.status_code == 302
        assert response.url == reverse("billing:enterprise_contact")


class TestWebhookViewIntegration:
    """Integration tests for webhook view with actual request processing."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up test environment."""
        self.client = Client()
        self.factory = RequestFactory()

    @patch("sbomify.apps.billing.views.stripe_client")
    def test_stripe_webhook_view_success(self, mock_stripe_client):
        """Test successful webhook processing through view."""
        mock_event = MagicMock()
        mock_event.type = "checkout.session.completed"
        mock_event.data.object = {"id": "cs_123", "payment_status": "paid"}
        mock_stripe_client.construct_webhook_event.return_value = mock_event

        with patch("sbomify.apps.billing.billing_processing.handle_checkout_completed") as mock_handler:
            response = self.client.post(
                reverse("billing:webhook"),
                data=json.dumps({"type": "checkout.session.completed"}),
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="test_signature",
            )

            assert response.status_code == 200
            mock_handler.assert_called_once_with(mock_event.data.object)

    @patch("sbomify.apps.billing.views.stripe_client")
    def test_stripe_webhook_view_missing_signature(self, mock_stripe_client):
        """Test webhook view with missing signature."""
        response = self.client.post(
            reverse("billing:webhook"),
            data=json.dumps({"type": "test.event"}),
            content_type="application/json",
        )

        assert response.status_code == 403

    @patch("sbomify.apps.billing.views.stripe_client")
    def test_stripe_webhook_view_invalid_signature(self, mock_stripe_client):
        """Test webhook view with invalid signature."""
        mock_stripe_client.construct_webhook_event.side_effect = stripe.error.SignatureVerificationError(
            "Invalid signature", "test_sig"
        )

        response = self.client.post(
            reverse("billing:webhook"),
            data=json.dumps({"type": "test.event"}),
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="invalid_signature",
        )

        assert response.status_code == 403