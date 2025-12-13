"""Tests for initial plan selection flow for new users."""

from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Member, Team

from .fixtures import (  # noqa: F401
    business_plan,
    community_plan,
    enterprise_plan,
    mock_stripe,
)

User = get_user_model()

pytestmark = pytest.mark.django_db


@pytest.fixture
def client() -> Client:
    """Create a test client."""
    return Client()


@pytest.fixture
def new_user() -> AbstractBaseUser:
    """Create a new user without any team membership."""
    user = User.objects.create_user(
        username="newuser",
        email="newuser@example.com",
        password="testpass123",
    )
    yield user
    user.delete()


@pytest.fixture
def team_without_plan(new_user: AbstractBaseUser) -> Team:
    """Create a team without a billing plan (simulating new user signup)."""
    team = Team.objects.create(name="Test Team")
    team.key = number_to_random_token(team.pk)
    team.has_selected_plan = False
    team.has_completed_wizard = False
    team.save()
    Member.objects.create(user=new_user, team=team, role="owner", is_default_team=True)
    yield team
    team.delete()


@pytest.fixture
def authenticated_session(client: Client, new_user: AbstractBaseUser, team_without_plan: Team) -> Client:
    """Create an authenticated client with session data."""
    client.force_login(new_user)
    session = client.session
    session["current_team"] = {
        "key": team_without_plan.key,
        "id": team_without_plan.id,
        "name": team_without_plan.name,
        "role": "owner",
        "has_selected_plan": False,
        "has_completed_wizard": False,
        "billing_plan": None,
    }
    session["user_teams"] = {
        team_without_plan.key: {
            "id": team_without_plan.id,
            "name": team_without_plan.name,
            "role": "owner",
            "is_default_team": True,
            "has_selected_plan": False,
            "has_completed_wizard": False,
            "billing_plan": None,
        }
    }
    session.save()
    return client


class TestInitialPlanSelectionView:
    """Tests for the initial_plan_selection view."""

    def test_requires_login(self, client: Client) -> None:
        """Test that plan selection page requires authentication."""
        response = client.get(reverse("billing:initial_plan_selection"))
        assert response.status_code == 302
        assert settings.LOGIN_URL in response.url

    def test_displays_plan_options(
        self,
        authenticated_session: Client,
        community_plan: BillingPlan,  # noqa: F811
        business_plan: BillingPlan,  # noqa: F811
        enterprise_plan: BillingPlan,  # noqa: F811
    ) -> None:
        """Test that the plan selection page displays all available plans."""
        response = authenticated_session.get(reverse("billing:initial_plan_selection"))
        assert response.status_code == 200
        content = response.content.decode()
        assert "Community" in content
        assert "Business" in content
        assert "Enterprise" in content

    def test_select_community_plan(
        self,
        authenticated_session: Client,
        team_without_plan: Team,
        community_plan: BillingPlan,  # noqa: F811
    ) -> None:
        """Test selecting the community plan."""
        response = authenticated_session.post(
            reverse("billing:initial_plan_selection"),
            {"plan": "community", "billing_period": "monthly"},
        )

        # Should redirect to onboarding wizard
        assert response.status_code == 302
        assert response.url == reverse("teams:onboarding_wizard")

        # Check team was updated
        team_without_plan.refresh_from_db()
        assert team_without_plan.billing_plan == "community"
        assert team_without_plan.has_selected_plan is True

        # Check success message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "Community" in str(messages[0])

    def test_select_business_plan_with_billing_enabled(
        self,
        authenticated_session: Client,
        team_without_plan: Team,
        business_plan: BillingPlan,  # noqa: F811
    ) -> None:
        """Test selecting the business plan with billing enabled."""
        # Mock billing enabled and stripe client
        with patch("sbomify.apps.billing.views.is_billing_enabled", return_value=True):
            mock_customer = MagicMock()
            mock_customer.id = "cus_test123"

            mock_subscription = MagicMock()
            mock_subscription.id = "sub_test123"
            mock_subscription.trial_end = 1234567890

            with patch(
                "sbomify.apps.billing.views.stripe_client.create_customer",
                return_value=mock_customer,
            ):
                with patch(
                    "sbomify.apps.billing.views.stripe_client.create_subscription",
                    return_value=mock_subscription,
                ):
                    response = authenticated_session.post(
                        reverse("billing:initial_plan_selection"),
                        {"plan": "business", "billing_period": "monthly"},
                    )

        # Should redirect to onboarding wizard
        assert response.status_code == 302
        assert response.url == reverse("teams:onboarding_wizard")

        # Check team was updated
        team_without_plan.refresh_from_db()
        assert team_without_plan.billing_plan == "business"
        assert team_without_plan.has_selected_plan is True
        assert team_without_plan.billing_plan_limits["stripe_customer_id"] == "cus_test123"
        assert team_without_plan.billing_plan_limits["is_trial"] is True

    def test_select_business_plan_with_billing_disabled(
        self,
        authenticated_session: Client,
        team_without_plan: Team,
        business_plan: BillingPlan,  # noqa: F811
    ) -> None:
        """Test selecting the business plan when billing is disabled."""
        with patch("sbomify.apps.billing.views.is_billing_enabled", return_value=False):
            response = authenticated_session.post(
                reverse("billing:initial_plan_selection"),
                {"plan": "business", "billing_period": "monthly"},
            )

        # Should redirect to onboarding wizard
        assert response.status_code == 302
        assert response.url == reverse("teams:onboarding_wizard")

        # Check team was updated without Stripe IDs
        team_without_plan.refresh_from_db()
        assert team_without_plan.billing_plan == "business"
        assert team_without_plan.has_selected_plan is True
        assert "stripe_customer_id" not in team_without_plan.billing_plan_limits

    def test_select_enterprise_redirects_to_contact(
        self,
        authenticated_session: Client,
        enterprise_plan: BillingPlan,  # noqa: F811
    ) -> None:
        """Test that selecting enterprise redirects to contact form."""
        response = authenticated_session.post(
            reverse("billing:initial_plan_selection"),
            {"plan": "enterprise", "billing_period": "monthly"},
        )

        # Should redirect to enterprise contact
        assert response.status_code == 302
        assert response.url == reverse("billing:enterprise_contact")

    def test_invalid_plan_shows_error(
        self,
        authenticated_session: Client,
    ) -> None:
        """Test that selecting an invalid plan shows an error."""
        response = authenticated_session.post(
            reverse("billing:initial_plan_selection"),
            {"plan": "invalid_plan", "billing_period": "monthly"},
        )

        # Should redirect back to plan selection
        assert response.status_code == 302
        assert response.url == reverse("billing:initial_plan_selection")

        # Check error message
        messages = list(get_messages(response.wsgi_request))
        assert len(messages) == 1
        assert "invalid" in str(messages[0]).lower()

    def test_redirects_if_plan_already_selected(
        self,
        client: Client,
        new_user: AbstractBaseUser,
        team_without_plan: Team,
    ) -> None:
        """Test that users with selected plan are redirected."""
        # Mark plan as selected
        team_without_plan.has_selected_plan = True
        team_without_plan.save()

        client.force_login(new_user)
        session = client.session
        session["current_team"] = {
            "key": team_without_plan.key,
            "has_selected_plan": True,
            "has_completed_wizard": False,
        }
        session.save()

        response = client.get(reverse("billing:initial_plan_selection"))

        # Should redirect to wizard if plan selected but wizard not complete
        assert response.status_code == 302
        assert response.url == reverse("teams:onboarding_wizard")


class TestDashboardRedirect:
    """Tests for dashboard redirect to plan selection."""

    def test_dashboard_redirects_to_plan_selection(
        self,
        authenticated_session: Client,
    ) -> None:
        """Test that dashboard redirects to plan selection for new users."""
        response = authenticated_session.get(reverse("core:dashboard"))

        # Should redirect to plan selection
        assert response.status_code == 302
        assert response.url == reverse("billing:initial_plan_selection")

    def test_dashboard_redirects_to_wizard_after_plan_selection(
        self,
        client: Client,
        new_user: AbstractBaseUser,
        team_without_plan: Team,
    ) -> None:
        """Test that dashboard redirects to wizard after plan is selected."""
        # Mark plan as selected
        team_without_plan.has_selected_plan = True
        team_without_plan.save()

        client.force_login(new_user)
        session = client.session
        session["current_team"] = {
            "key": team_without_plan.key,
            "has_selected_plan": True,
            "has_completed_wizard": False,
        }
        session.save()

        response = client.get(reverse("core:dashboard"))

        # Should redirect to wizard
        assert response.status_code == 302
        assert response.url == reverse("teams:onboarding_wizard")

    def test_dashboard_shows_content_after_all_complete(
        self,
        client: Client,
        new_user: AbstractBaseUser,
        team_without_plan: Team,
        community_plan: BillingPlan,  # noqa: F811
    ) -> None:
        """Test that dashboard shows content when plan and wizard are complete."""
        # Mark everything as complete
        team_without_plan.has_selected_plan = True
        team_without_plan.has_completed_wizard = True
        team_without_plan.billing_plan = "community"
        team_without_plan.save()

        client.force_login(new_user)
        session = client.session
        session["current_team"] = {
            "key": team_without_plan.key,
            "id": team_without_plan.id,
            "has_selected_plan": True,
            "has_completed_wizard": True,
            "billing_plan": "community",
        }
        session["user_teams"] = {
            team_without_plan.key: {
                "id": team_without_plan.id,
                "name": team_without_plan.name,
                "role": "owner",
                "is_default_team": True,
                "has_selected_plan": True,
                "has_completed_wizard": True,
                "billing_plan": "community",
            }
        }
        session.save()

        response = client.get(reverse("core:dashboard"))

        # Should show dashboard content
        assert response.status_code == 200


class TestTeamCreationWithoutPlan:
    """Tests for team creation without automatic plan setup."""

    def test_new_team_has_no_plan(self) -> None:
        """Test that newly created teams have no billing plan."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

        # Simulate the team creation flow
        from sbomify.apps.teams.utils import create_user_team_and_subscription

        with patch("sbomify.apps.billing.config.is_billing_enabled", return_value=True):
            team = create_user_team_and_subscription(user)

        if team:
            # Team should have no billing plan initially
            assert team.billing_plan is None
            assert team.has_selected_plan is False

            # Cleanup
            team.delete()
        user.delete()

    def test_session_includes_has_selected_plan(
        self,
        new_user: AbstractBaseUser,
        team_without_plan: Team,
    ) -> None:
        """Test that session data includes has_selected_plan field."""
        from sbomify.apps.teams.utils import get_user_teams

        user_teams = get_user_teams(new_user)
        team_data = user_teams.get(team_without_plan.key, {})

        assert "has_selected_plan" in team_data
        assert team_data["has_selected_plan"] is False
