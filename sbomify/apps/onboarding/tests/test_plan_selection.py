"""Tests for onboarding plan selection and trial expiration downgrade."""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Member, Team

User = get_user_model()
pytestmark = pytest.mark.django_db


# ── Helpers ───────────────────────────────────────────────────────────


def _wizard_plan_url(**params):
    """Build the wizard plan step URL."""
    url = reverse("teams:onboarding_wizard") + "?step=plan"
    for key, value in params.items():
        url += f"&{key}={value}"
    return url


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def community_plan():
    plan, _ = BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "description": "Free plan",
            "max_products": 1,
            "max_projects": 1,
            "max_components": 5,
        },
    )
    return plan


@pytest.fixture
def business_plan():
    plan, _ = BillingPlan.objects.get_or_create(
        key="business",
        defaults={
            "name": "Business",
            "description": "For growing teams",
            "max_products": 10,
            "max_projects": 20,
            "max_components": 100,
            "stripe_product_id": "prod_test",
            "stripe_price_monthly_id": "price_monthly_test",
            "stripe_price_annual_id": "price_annual_test",
        },
    )
    return plan


@pytest.fixture
def enterprise_plan():
    plan, _ = BillingPlan.objects.get_or_create(
        key="enterprise",
        defaults={
            "name": "Enterprise",
            "description": "Custom pricing",
        },
    )
    return plan


@pytest.fixture
def billing_enabled(settings):
    settings.BILLING = True
    return settings


@pytest.fixture
def billing_disabled(settings):
    settings.BILLING = False
    return settings


@pytest.fixture
def new_user(community_plan):
    """Simulate a freshly signed-up user whose workspace has NOT selected a plan."""
    user = User.objects.create_user(username="newuser", email="new@example.com", password="testpass123")
    team = Team.objects.create(
        name="New Team",
        billing_plan="community",
        has_completed_wizard=True,
        has_selected_billing_plan=False,
        billing_plan_limits={
            "max_products": community_plan.max_products,
            "max_projects": community_plan.max_projects,
            "max_components": community_plan.max_components,
            "subscription_status": "active",
        },
    )
    team.key = number_to_random_token(team.pk)
    team.save()
    Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
    return user, team


@pytest.fixture
def existing_user(community_plan):
    """Simulate an existing user whose workspace already selected a plan."""
    user = User.objects.create_user(username="existinguser", email="existing@example.com", password="testpass123")
    team = Team.objects.create(
        name="Existing Team",
        billing_plan="community",
        has_completed_wizard=True,
        has_selected_billing_plan=True,
    )
    team.key = number_to_random_token(team.pk)
    team.save()
    Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
    return user, team


@pytest.fixture
def authed_client(new_user):
    """Return an authenticated client with session set up for the new user."""
    user, team = new_user
    client = Client()
    client.login(username="newuser", password="testpass123")
    session = client.session
    session["current_team"] = {
        "key": team.key,
        "name": team.name,
        "role": "owner",
        "has_completed_wizard": True,
    }
    session.save()
    return client, user, team


# ── Plan Selection View Tests (wizard step) ──────────────────────────


class TestOnboardingPlanSelectionGet:
    def test_renders_plan_selection(self, billing_enabled, authed_client, business_plan, enterprise_plan):
        client, user, team = authed_client
        resp = client.get(_wizard_plan_url())
        assert resp.status_code == 200
        assert b"Choose Your Plan" in resp.content

    def test_redirects_if_already_selected(self, billing_enabled, existing_user):
        user, team = existing_user
        client = Client()
        client.login(username="existinguser", password="testpass123")
        session = client.session
        session["current_team"] = {
            "key": team.key,
            "name": team.name,
            "role": "owner",
            "has_completed_wizard": True,
        }
        session.save()
        resp = client.get(_wizard_plan_url())
        assert resp.status_code == 302
        assert "/dashboard" in resp.url or resp.url == "/"

    def test_plan_hint_from_get_param(self, billing_enabled, authed_client, business_plan, enterprise_plan):
        client, user, team = authed_client
        resp = client.get(_wizard_plan_url(plan="business"))
        assert resp.status_code == 200
        assert b"business" in resp.content

    def test_requires_login(self):
        client = Client()
        resp = client.get(_wizard_plan_url())
        assert resp.status_code == 302
        assert "login" in resp.url or "accounts" in resp.url


class TestOnboardingPlanSelectionPost:
    def test_select_community(self, billing_enabled, authed_client, community_plan):
        client, user, team = authed_client
        resp = client.post(reverse("teams:onboarding_wizard"), {"plan": "community"})
        assert resp.status_code == 302

        team.refresh_from_db()
        assert team.has_selected_billing_plan is True
        assert team.billing_plan == "community"

    @patch("sbomify.apps.teams.utils.setup_trial_subscription")
    def test_select_business_triggers_trial(self, mock_setup, billing_enabled, authed_client, business_plan):
        mock_setup.return_value = True
        client, user, team = authed_client

        resp = client.post(reverse("teams:onboarding_wizard"), {"plan": "business"})
        assert resp.status_code == 302

        mock_setup.assert_called_once_with(user, team)

        team.refresh_from_db()
        assert team.has_selected_billing_plan is True

    @patch("sbomify.apps.teams.utils.setup_trial_subscription")
    def test_select_business_fallback_on_failure(self, mock_setup, billing_enabled, authed_client, business_plan):
        mock_setup.return_value = False
        client, user, team = authed_client

        resp = client.post(reverse("teams:onboarding_wizard"), {"plan": "business"})
        assert resp.status_code == 302
        assert "step=plan" in resp.url

        team.refresh_from_db()
        assert team.has_selected_billing_plan is False

    def test_select_enterprise_redirects_to_contact(self, billing_enabled, authed_client, enterprise_plan):
        client, user, team = authed_client
        resp = client.post(reverse("teams:onboarding_wizard"), {"plan": "enterprise"})
        assert resp.status_code == 302
        assert "enterprise-contact" in resp.url

        team.refresh_from_db()
        assert team.has_selected_billing_plan is True

    def test_invalid_plan_rejected(self, billing_enabled, authed_client):
        client, user, team = authed_client
        resp = client.post(reverse("teams:onboarding_wizard"), {"plan": "invalid"})
        assert resp.status_code == 302

        team.refresh_from_db()
        assert team.has_selected_billing_plan is False

    def test_idempotent_already_selected(self, billing_enabled, existing_user):
        user, team = existing_user
        client = Client()
        client.login(username="existinguser", password="testpass123")
        session = client.session
        session["current_team"] = {
            "key": team.key,
            "has_completed_wizard": True,
        }
        session.save()

        resp = client.post(reverse("teams:onboarding_wizard"), {"plan": "business"})
        assert resp.status_code == 302
        assert "/dashboard" in resp.url or resp.url == "/"


class TestBillingDisabled:
    def test_get_redirects_to_dashboard(self, billing_disabled, authed_client):
        client, user, team = authed_client
        resp = client.get(_wizard_plan_url())
        assert resp.status_code == 302

    def test_post_redirects_to_dashboard(self, billing_disabled, authed_client):
        client, user, team = authed_client
        resp = client.post(reverse("teams:onboarding_wizard"), {"plan": "community"})
        assert resp.status_code == 302


# ── Legacy URL Redirect Tests ────────────────────────────────────────


class TestLegacyPlanUrl:
    def test_legacy_get_redirects_to_wizard(self, billing_enabled, authed_client):
        client, user, team = authed_client
        resp = client.get("/onboarding/select-plan/")
        assert resp.status_code == 302
        assert "step=plan" in resp.url

    def test_legacy_post_redirects_to_wizard(self, billing_enabled, authed_client):
        client, user, team = authed_client
        resp = client.post("/onboarding/select-plan/", {"plan": "community"})
        assert resp.status_code == 302
        assert "step=plan" in resp.url

    def test_legacy_get_billing_disabled_redirects_to_dashboard(self, billing_disabled, authed_client):
        client, user, team = authed_client
        resp = client.get("/onboarding/select-plan/")
        assert resp.status_code == 302


# ── Default Plan Tests ────────────────────────────────────────────────


class TestDefaultPlanOnSignup:
    @patch("sbomify.apps.teams.utils.stripe_client")
    def test_new_user_gets_community_not_trial(self, mock_stripe, community_plan):
        """New users should default to community, not auto-Business trial."""
        from sbomify.apps.teams.utils import create_user_team_and_subscription

        user = User.objects.create_user(username="brandnew", email="brand@example.com", password="testpass")
        team = create_user_team_and_subscription(user)

        assert team.billing_plan == "community"
        assert team.billing_plan_limits.get("is_trial") is None
        mock_stripe.create_customer.assert_not_called()
        mock_stripe.create_subscription.assert_not_called()


# ── Trial Expiration Downgrade Tests ──────────────────────────────────


class TestTrialExpirationDowngrade:
    def test_expired_trial_downgrades_to_community(self, community_plan, business_plan):
        """When trial expires, team should be downgraded to community plan."""
        from sbomify.apps.billing.billing_processing import handle_trial_period

        expired_ts = int((timezone.now() - timezone.timedelta(days=1)).timestamp())
        team = Team.objects.create(
            name="Trial Team",
            billing_plan="business",
            billing_plan_limits={
                "stripe_customer_id": "cus_test",
                "stripe_subscription_id": "sub_test",
                "subscription_status": "trialing",
                "is_trial": True,
                "trial_end": expired_ts,
            },
        )
        team.key = number_to_random_token(team.pk)
        team.save()

        mock_sub = MagicMock()
        mock_sub.id = "sub_test"
        mock_sub.status = "trialing"
        mock_sub.trial_end = expired_ts
        mock_sub.metadata = {"plan_key": "business"}

        with (
            patch("sbomify.apps.billing.billing_processing.handle_community_downgrade_visibility"),
            patch("sbomify.apps.billing.billing_processing.notify_team_owners"),
        ):
            handle_trial_period(mock_sub, team)

        team.refresh_from_db()
        assert team.billing_plan == "community"
        limits = team.billing_plan_limits
        assert limits["is_trial"] is False
        assert limits["subscription_status"] == "canceled"
        assert limits["max_products"] == community_plan.max_products

    def test_active_trial_stays_on_business(self, community_plan, business_plan):
        """Trial with days remaining should stay on business plan."""
        from sbomify.apps.billing.billing_processing import handle_trial_period

        future_ts = int((timezone.now() + timezone.timedelta(days=7)).timestamp())
        team = Team.objects.create(
            name="Active Trial Team",
            billing_plan="business",
            billing_plan_limits={
                "stripe_customer_id": "cus_test2",
                "stripe_subscription_id": "sub_test2",
                "subscription_status": "trialing",
                "is_trial": True,
                "trial_end": future_ts,
            },
        )
        team.key = number_to_random_token(team.pk)
        team.save()

        mock_sub = MagicMock()
        mock_sub.id = "sub_test2"
        mock_sub.status = "trialing"
        mock_sub.trial_end = future_ts
        mock_sub.metadata = {"plan_key": "business"}

        with patch("sbomify.apps.billing.billing_processing.notify_team_owners"):
            handle_trial_period(mock_sub, team)

        team.refresh_from_db()
        assert team.billing_plan == "business"


# ── Redirect Tests ────────────────────────────────────────────────────


class TestPlanSelectionRedirects:
    def test_home_redirects_wizard_incomplete_to_welcome(self, billing_enabled, new_user):
        """Brand new user (wizard not done) goes to Welcome, not Plan."""
        user, team = new_user
        client = Client()
        client.login(username="newuser", password="testpass123")
        session = client.session
        session["current_team"] = {
            "key": team.key,
            "name": team.name,
            "role": "owner",
            "has_completed_wizard": False,
        }
        session.save()

        resp = client.get("/")
        assert resp.status_code == 302
        assert "onboarding" in resp.url
        assert "step=plan" not in resp.url

    def test_home_redirects_wizard_done_to_plan_selection(self, billing_enabled, new_user):
        """User who finished wizard but hasn't picked a plan goes to Plan step."""
        user, team = new_user
        client = Client()
        client.login(username="newuser", password="testpass123")
        session = client.session
        session["current_team"] = {
            "key": team.key,
            "name": team.name,
            "role": "owner",
            "has_completed_wizard": True,
        }
        session.save()

        resp = client.get("/")
        assert resp.status_code == 302
        assert "step=plan" in resp.url

    def test_home_skips_existing_user(self, billing_enabled, existing_user):
        user, team = existing_user
        client = Client()
        client.login(username="existinguser", password="testpass123")
        session = client.session
        session["current_team"] = {
            "key": team.key,
            "name": team.name,
            "role": "owner",
            "has_completed_wizard": True,
        }
        session.save()

        resp = client.get("/")
        assert resp.status_code == 302
        assert "step=plan" not in resp.url

    def test_dashboard_redirects_new_user_to_plan_selection(self, billing_enabled, authed_client):
        client, user, team = authed_client
        resp = client.get("/dashboard")
        assert resp.status_code == 302
        assert "step=plan" in resp.url

    def test_dashboard_shows_for_existing_user(self, billing_enabled, existing_user):
        user, team = existing_user
        client = Client()
        client.login(username="existinguser", password="testpass123")
        session = client.session
        session["current_team"] = {
            "key": team.key,
            "name": team.name,
            "role": "owner",
            "has_completed_wizard": True,
        }
        session.save()

        resp = client.get("/dashboard")
        assert resp.status_code == 200
