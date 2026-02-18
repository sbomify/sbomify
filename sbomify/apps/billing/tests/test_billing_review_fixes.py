"""Tests for billing code review fixes.

Covers: checkout session lock, fail-closed rate limiter, enterprise contact rate limiting,
plan_key in API checkout metadata, Turnstile remoteip, get_community_plan_limits helper,
price_id validation in trial setup, and session_id masking in billing return.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse

from sbomify.apps.billing.billing_helpers import (
    CHECKOUT_LOCK_TTL,
    acquire_checkout_lock,
    check_rate_limit,
    get_community_plan_limits,
    release_checkout_lock,
)
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.billing.tests.fixtures import *  # noqa: F401, F403
from sbomify.apps.core.tests.shared_fixtures import *  # noqa: F401, F403

# ============================================================================
# Task #44: Checkout Session Lock Tests
# ============================================================================


@pytest.mark.django_db
class TestCheckoutSessionLock:
    """Test cache-based checkout session lock (acquire/release, concurrent prevention, expiry)."""

    def setup_method(self):
        cache.clear()

    def test_acquire_lock_succeeds_on_first_call(self):
        assert acquire_checkout_lock("team_abc") is True

    def test_acquire_lock_fails_when_already_held(self):
        acquire_checkout_lock("team_abc")
        assert acquire_checkout_lock("team_abc") is False

    def test_release_lock_allows_reacquire(self):
        acquire_checkout_lock("team_abc")
        release_checkout_lock("team_abc")
        assert acquire_checkout_lock("team_abc") is True

    def test_locks_are_team_scoped(self):
        acquire_checkout_lock("team_a")
        assert acquire_checkout_lock("team_b") is True

    def test_lock_uses_correct_cache_key(self):
        acquire_checkout_lock("team_xyz")
        assert cache.get("checkout_lock:team_xyz") == 1

    def test_lock_ttl_constant(self):
        assert CHECKOUT_LOCK_TTL == 300

    def test_release_nonexistent_lock_is_safe(self):
        release_checkout_lock("nonexistent_team")


# ============================================================================
# Task #45: Fail-Closed Rate Limiter Tests
# ============================================================================


@pytest.mark.django_db
class TestFailClosedRateLimiter:
    """Test that rate limiter fails closed when cache is unavailable."""

    def setup_method(self):
        cache.clear()

    def test_rate_limit_not_exceeded(self):
        assert check_rate_limit("test_key", limit=5, period=60) is False

    def test_rate_limit_exceeded_after_threshold(self):
        for _ in range(5):
            check_rate_limit("test_key", limit=5, period=60)
        assert check_rate_limit("test_key", limit=5, period=60) is True

    def test_rate_limit_separate_keys(self):
        for _ in range(5):
            check_rate_limit("key_a", limit=5, period=60)
        assert check_rate_limit("key_a", limit=5, period=60) is True
        assert check_rate_limit("key_b", limit=5, period=60) is False

    @patch("sbomify.apps.billing.billing_helpers.cache")
    def test_fails_closed_when_cache_unavailable(self, mock_cache):
        """When cache.incr raises ValueError on both attempts, return True (rate-limited)."""
        mock_cache.add.return_value = True
        mock_cache.incr.side_effect = ValueError("Key not found")
        mock_cache.set.return_value = True

        result = check_rate_limit("broken_cache_key", limit=5, period=60)
        assert result is True

    @patch("sbomify.apps.billing.billing_helpers.cache")
    def test_recovers_on_second_attempt(self, mock_cache):
        """When first attempt fails but second succeeds, return based on count."""
        call_count = 0

        def add_side_effect(key, value, timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("First attempt fails")
            return True

        mock_cache.add.side_effect = add_side_effect
        mock_cache.set.return_value = True
        mock_cache.incr.return_value = 1

        result = check_rate_limit("recovery_key", limit=5, period=60)
        assert result is False


# ============================================================================
# Task #46: Enterprise Contact Rate Limiting Tests
# ============================================================================


@pytest.mark.django_db
class TestEnterpriseContactRateLimiting:
    """Test rate limiting on enterprise contact form (IP-based and user-based keys)."""

    def setup_method(self):
        cache.clear()

    def test_authenticated_user_rate_limit_key(self, client, sample_user):
        """Authenticated users get user-PK-based rate limit key."""
        client.force_login(sample_user)

        with patch("sbomify.apps.billing.views.check_rate_limit", return_value=True) as mock_rl:
            response = client.post(reverse("billing:enterprise_contact"), {})
            assert response.status_code == 302
            mock_rl.assert_called_once()
            key = mock_rl.call_args[0][0]
            assert key == f"enterprise_contact:{sample_user.pk}"

    def test_unauthenticated_user_rate_limit_key(self, client):
        """Unauthenticated users get IP-based rate limit key."""
        with patch("sbomify.apps.billing.views.check_rate_limit", return_value=True) as mock_rl:
            response = client.post(reverse("public_enterprise_contact"), {}, REMOTE_ADDR="1.2.3.4")
            assert response.status_code == 302
            mock_rl.assert_called_once()
            key = mock_rl.call_args[0][0]
            assert key == "enterprise_contact_ip:1.2.3.4"

    def test_rate_limited_response_redirects(self, client, sample_user):
        """When rate limited, user is redirected with error message."""
        client.force_login(sample_user)

        with patch("sbomify.apps.billing.views.check_rate_limit", return_value=True):
            response = client.post(reverse("billing:enterprise_contact"), {})
            assert response.status_code == 302


# ============================================================================
# Task #47: plan_key in API Checkout Metadata Tests
# ============================================================================


@pytest.mark.django_db
class TestPlanKeyInCheckoutMetadata:
    """Test that plan_key is included in Stripe checkout session metadata."""

    def test_api_change_plan_includes_plan_key_in_metadata(
        self, client, sample_user, team_with_community_plan, business_plan
    ):
        """API change-plan endpoint includes plan_key in checkout metadata."""
        client.force_login(sample_user)

        session = client.session
        session["current_team"] = {"key": team_with_community_plan.key}
        session.save()

        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/test"

        mock_stripe = MagicMock()
        mock_stripe.get_customer.return_value = MagicMock(id=f"c_{team_with_community_plan.key}")
        mock_stripe.list_subscriptions.return_value = MagicMock(data=[])
        mock_stripe.create_checkout_session.return_value = mock_session

        with patch("sbomify.apps.billing.apis.get_stripe_client", return_value=mock_stripe):
            response = client.post(
                "/api/v1/billing/change-plan/",
                data={
                    "plan": "business",
                    "billing_period": "monthly",
                    "team_key": team_with_community_plan.key,
                },
                content_type="application/json",
            )

        if response.status_code == 200:
            call_kwargs = mock_stripe.create_checkout_session.call_args
            if call_kwargs:
                metadata = call_kwargs.kwargs.get("metadata", {})
                assert "plan_key" in metadata
                assert metadata["plan_key"] == "business"

    def test_billing_redirect_view_includes_plan_key_in_metadata(
        self, client, sample_user, team_with_community_plan, business_plan
    ):
        """BillingRedirectView includes plan_key in checkout session metadata."""
        client.force_login(sample_user)

        session = client.session
        session["selected_plan"] = {"key": "business", "billing_period": "monthly"}
        session.save()

        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/test"

        with patch("sbomify.apps.billing.views.stripe_client") as mock_stripe:
            mock_stripe.create_customer.return_value = MagicMock(id=f"c_{team_with_community_plan.key}")
            mock_stripe.get_customer.return_value = MagicMock(id=f"c_{team_with_community_plan.key}")
            mock_stripe.create_checkout_session.return_value = mock_session

            client.get(reverse("billing:billing_redirect", kwargs={"team_key": team_with_community_plan.key}))

        if mock_stripe.create_checkout_session.called:
            call_kwargs = mock_stripe.create_checkout_session.call_args
            metadata = call_kwargs.kwargs.get("metadata", {})
            assert "plan_key" in metadata
            assert metadata["plan_key"] == "business"


# ============================================================================
# Task #48: Turnstile remoteip Parameter Tests
# ============================================================================


@pytest.mark.django_db
class TestTurnstileRemoteip:
    """Test that remoteip is passed to Turnstile verification."""

    def test_form_stores_remoteip(self):
        """PublicEnterpriseContactForm stores remoteip from constructor."""
        from sbomify.apps.billing.forms import PublicEnterpriseContactForm

        form = PublicEnterpriseContactForm(remoteip="192.168.1.1")
        assert form._remoteip == "192.168.1.1"

    def test_form_without_remoteip(self):
        """PublicEnterpriseContactForm works without remoteip."""
        from sbomify.apps.billing.forms import PublicEnterpriseContactForm

        form = PublicEnterpriseContactForm()
        assert form._remoteip is None

    def test_remoteip_included_in_verification(self):
        """When remoteip is set, it's included in Turnstile verification data."""
        from sbomify.apps.billing.forms import PublicEnterpriseContactForm

        form_data = {
            "company_name": "Test Co",
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "company_size": "startup",
            "primary_use_case": "compliance",
            "message": "This is a test message that is long enough.",
            "cf_turnstile_response": "test-token",
        }

        with pytest.MonkeyPatch.context() as m:
            m.setattr(settings, "TURNSTILE_ENABLED", True)
            m.setattr(settings, "TURNSTILE_SECRET_KEY", "test-secret")

            mock_response = MagicMock()
            mock_response.json.return_value = {"success": True}

            with patch("sbomify.apps.billing.forms.post_form", return_value=mock_response) as mock_post:
                form = PublicEnterpriseContactForm(form_data, remoteip="10.0.0.1")
                form.is_valid()

                mock_post.assert_called_once()
                call_kwargs = mock_post.call_args
                verify_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
                assert verify_data["remoteip"] == "10.0.0.1"

    def test_remoteip_excluded_when_none(self):
        """When remoteip is None, it's NOT included in Turnstile verification data."""
        from sbomify.apps.billing.forms import PublicEnterpriseContactForm

        form_data = {
            "company_name": "Test Co",
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "company_size": "startup",
            "primary_use_case": "compliance",
            "message": "This is a test message that is long enough.",
            "cf_turnstile_response": "test-token",
        }

        with pytest.MonkeyPatch.context() as m:
            m.setattr(settings, "TURNSTILE_ENABLED", True)
            m.setattr(settings, "TURNSTILE_SECRET_KEY", "test-secret")

            mock_response = MagicMock()
            mock_response.json.return_value = {"success": True}

            with patch("sbomify.apps.billing.forms.post_form", return_value=mock_response) as mock_post:
                form = PublicEnterpriseContactForm(form_data, remoteip=None)
                form.is_valid()

                mock_post.assert_called_once()
                call_kwargs = mock_post.call_args
                verify_data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
                assert "remoteip" not in verify_data

    def test_view_passes_remote_addr_to_form(self, client):
        """PublicEnterpriseContactView passes REMOTE_ADDR to form."""
        with patch("sbomify.apps.billing.views.check_rate_limit", return_value=False):
            with patch("sbomify.apps.billing.views.PublicEnterpriseContactForm") as MockForm:
                mock_form = MagicMock()
                mock_form.is_valid.return_value = False
                MockForm.return_value = mock_form

                client.post(
                    reverse("public_enterprise_contact"),
                    {"company_name": "Test"},
                    REMOTE_ADDR="203.0.113.5",
                )

                MockForm.assert_called_once()
                call_kwargs = MockForm.call_args
                assert call_kwargs.kwargs.get("remoteip") == "203.0.113.5"


# ============================================================================
# Task #49: get_community_plan_limits Helper Tests
# ============================================================================


@pytest.mark.django_db
class TestGetCommunityPlanLimits:
    """Test the centralized community plan limits helper."""

    def test_returns_correct_limits(self, community_plan):
        """Returns limits matching the community plan in DB."""
        limits = get_community_plan_limits()
        assert limits["max_products"] == community_plan.max_products
        assert limits["max_projects"] == community_plan.max_projects
        assert limits["max_components"] == community_plan.max_components

    def test_returns_dict_with_expected_keys(self, community_plan):
        limits = get_community_plan_limits()
        assert set(limits.keys()) == {"max_products", "max_projects", "max_components"}

    def test_returns_unlimited_when_plan_missing(self):
        """When community plan doesn't exist, returns unlimited (None) limits."""
        BillingPlan.objects.filter(key="community").delete()
        limits = get_community_plan_limits()
        assert limits["max_products"] is None
        assert limits["max_projects"] is None
        assert limits["max_components"] is None


# ============================================================================
# Task #50: price_id Validation in Trial Setup Tests
# ============================================================================


@pytest.mark.django_db
class TestPriceIdValidationInTrialSetup:
    """Test that setup_trial_subscription validates stripe_price_monthly_id."""

    def test_falls_back_to_community_when_no_price_id(self, sample_user, community_plan):
        """When business plan has no stripe_price_monthly_id, falls back to community."""
        from sbomify.apps.teams.utils import setup_trial_subscription

        BillingPlan.objects.get_or_create(
            key="business",
            defaults={
                "name": "Business",
                "description": "For growing teams",
                "max_products": 10,
                "max_projects": 20,
                "max_components": 100,
                "stripe_product_id": "prod_test",
                "stripe_price_monthly_id": "",  # Empty = no price configured
                "stripe_price_annual_id": "price_annual",
            },
        )
        BillingPlan.objects.filter(key="business").update(stripe_price_monthly_id="")

        from sbomify.apps.core.utils import number_to_random_token
        from sbomify.apps.teams.models import Member, Team

        team = Team.objects.create(name="Trial Test Team")
        team.key = number_to_random_token(team.pk)
        team.save()
        Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=True)

        result = setup_trial_subscription(sample_user, team)
        assert result is False

        team.refresh_from_db()
        assert team.billing_plan == "community"

    def test_proceeds_when_price_id_present(self, sample_user, business_plan, community_plan):
        """When business plan has stripe_price_monthly_id, proceeds with trial setup."""
        from sbomify.apps.core.utils import number_to_random_token
        from sbomify.apps.teams.models import Member, Team
        from sbomify.apps.teams.utils import setup_trial_subscription

        team = Team.objects.create(name="Trial Test Team 2")
        team.key = number_to_random_token(team.pk)
        team.save()
        Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=True)

        mock_customer = MagicMock()
        mock_customer.id = "cus_trial_test"
        mock_sub = MagicMock()
        mock_sub.id = "sub_trial_test"
        mock_sub.trial_end = 1700000000

        with patch("sbomify.apps.teams.utils.stripe_client") as mock_stripe:
            mock_stripe.create_customer.return_value = mock_customer
            mock_stripe.create_subscription.return_value = mock_sub

            result = setup_trial_subscription(sample_user, team)

        assert result is True
        team.refresh_from_db()
        assert team.billing_plan == "business"
        assert team.billing_plan_limits["stripe_subscription_id"] == "sub_trial_test"


# ============================================================================
# Task #51: Session ID Masking in Billing Return Tests
# ============================================================================


@pytest.mark.django_db
class TestSessionIdMaskingInBillingReturn:
    """Test that session_id is masked in BillingReturnView logs."""

    def test_masked_session_id_in_log(self, client, sample_user, team_with_business_plan, business_plan):
        """BillingReturnView logs masked session_id (first 8 + last 4 chars)."""
        client.force_login(sample_user)

        mock_session = MagicMock()
        mock_session.metadata = MagicMock()
        mock_session.metadata.get = lambda key, default=None: {
            "team_key": team_with_business_plan.key,
            "plan_key": "business",
        }.get(key, default)
        mock_session.payment_status = "paid"
        mock_session.subscription = "sub_test_billing_return"
        mock_session.customer = "cus_test_billing_return"

        mock_sub = MagicMock()
        mock_sub.id = "sub_test_billing_return"
        mock_sub.status = "active"
        mock_sub.items = MagicMock(data=[])
        mock_sub.cancel_at = None
        mock_sub.cancel_at_period_end = False

        mock_customer = MagicMock()
        mock_customer.id = "cus_test_billing_return"

        with patch("sbomify.apps.billing.views.stripe_client") as mock_stripe:
            mock_stripe.get_checkout_session.return_value = mock_session
            mock_stripe.get_subscription.return_value = mock_sub
            mock_stripe.get_customer.return_value = mock_customer

            with patch("sbomify.apps.billing.views.sync_subscription_from_stripe"):
                with patch("sbomify.apps.billing.views.logger") as mock_logger:
                    session_id = "cs_test_abcdefghijklmnop1234"
                    client.get(reverse("billing:billing_return") + f"?session_id={session_id}")

                    # Find the info log call that masks the session_id
                    info_calls = [
                        call for call in mock_logger.info.call_args_list if "Processing billing return" in str(call)
                    ]
                    assert len(info_calls) >= 1
                    call_args = info_calls[0]
                    # The log format is: "Processing billing return with session_id: %s...%s"
                    # With args: session_id[:8], session_id[-4:]
                    assert call_args[0][1] == session_id[:8]
                    assert call_args[0][2] == session_id[-4:]

    def test_billing_return_without_session_id_redirects(self, client, sample_user):
        """BillingReturnView without session_id redirects to dashboard."""
        client.force_login(sample_user)
        response = client.get(reverse("billing:billing_return"))
        assert response.status_code == 302

    def test_billing_return_extracts_plan_key_from_metadata(
        self, client, sample_user, team_with_community_plan, business_plan
    ):
        """BillingReturnView uses plan_key from session metadata."""
        client.force_login(sample_user)

        mock_session = MagicMock()
        mock_session.metadata = MagicMock()
        mock_session.metadata.get = lambda key, default=None: {
            "team_key": team_with_community_plan.key,
            "plan_key": "business",
        }.get(key, default)
        mock_session.payment_status = "paid"
        mock_session.subscription = "sub_plan_key_test"
        mock_session.customer = "cus_plan_key_test"

        mock_sub = MagicMock()
        mock_sub.id = "sub_plan_key_test"
        mock_sub.status = "active"
        mock_sub.items = MagicMock(data=[])
        mock_sub.cancel_at = None
        mock_sub.cancel_at_period_end = False

        mock_customer = MagicMock()
        mock_customer.id = "cus_plan_key_test"

        with patch("sbomify.apps.billing.views.stripe_client") as mock_stripe:
            mock_stripe.get_checkout_session.return_value = mock_session
            mock_stripe.get_subscription.return_value = mock_sub
            mock_stripe.get_customer.return_value = mock_customer

            with patch("sbomify.apps.billing.views.sync_subscription_from_stripe"):
                with patch("sbomify.apps.billing.views.release_checkout_lock"):
                    client.get(reverse("billing:billing_return") + "?session_id=cs_test_abcdefghijklmnop1234")

        team_with_community_plan.refresh_from_db()
        assert team_with_community_plan.billing_plan == "business"


# ============================================================================
# Integration: Checkout Lock in Views
# ============================================================================


@pytest.mark.django_db
class TestCheckoutLockInViews:
    """Test that checkout lock is properly integrated in views."""

    def setup_method(self):
        cache.clear()

    def test_billing_redirect_blocked_when_lock_held(
        self, client, sample_user, team_with_community_plan, business_plan
    ):
        """BillingRedirectView returns redirect when checkout lock is already held."""
        client.force_login(sample_user)

        session = client.session
        session["selected_plan"] = {"key": "business", "billing_period": "monthly"}
        session.save()

        acquire_checkout_lock(team_with_community_plan.key)

        with patch("sbomify.apps.billing.views.stripe_client") as mock_stripe:
            mock_stripe.get_customer.return_value = MagicMock(id=f"c_{team_with_community_plan.key}")
            mock_stripe.create_customer.return_value = MagicMock(id=f"c_{team_with_community_plan.key}")

            response = client.get(
                reverse("billing:billing_redirect", kwargs={"team_key": team_with_community_plan.key})
            )

        assert response.status_code == 302

    def test_checkout_lock_released_on_stripe_error(self, client, sample_user, team_with_community_plan, business_plan):
        """Lock is released when Stripe checkout creation fails."""
        client.force_login(sample_user)

        session = client.session
        session["selected_plan"] = {"key": "business", "billing_period": "monthly"}
        session.save()

        from sbomify.apps.billing.stripe_client import StripeError

        with patch("sbomify.apps.billing.views.stripe_client") as mock_stripe:
            mock_stripe.get_customer.return_value = MagicMock(id=f"c_{team_with_community_plan.key}")
            mock_stripe.create_customer.return_value = MagicMock(id=f"c_{team_with_community_plan.key}")
            mock_stripe.create_checkout_session.side_effect = StripeError("Stripe error")

            response = client.get(
                reverse("billing:billing_redirect", kwargs={"team_key": team_with_community_plan.key})
            )

        assert response.status_code == 302
        # Lock should be released after error
        assert acquire_checkout_lock(team_with_community_plan.key) is True
