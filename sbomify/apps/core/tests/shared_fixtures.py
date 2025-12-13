"""
Shared test fixtures and utilities for sbomify tests.

This module provides reusable fixtures and helper functions that are commonly
used across different test files to reduce duplication and ensure consistency.
"""

from typing import Any, Dict, Generator

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client, TestCase

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.tests.fixtures import guest_user, sample_user  # noqa: F401
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.sboms.tests.test_views import setup_test_session
from sbomify.apps.teams.models import Member, Team

# ============================================================================
# Authentication & API Testing Fixtures
# ============================================================================


@pytest.fixture
def authenticated_api_client(sample_user: AbstractBaseUser) -> Generator[tuple[Client, AccessToken], Any, None]:  # noqa: F811
    """
    Create an authenticated API client with access token for API testing.

    Returns:
        Tuple of (client, access_token) for API testing
    """
    token_str = create_personal_access_token(sample_user)
    access_token = AccessToken.objects.create(user=sample_user, encoded_token=token_str, description="Test API Token")

    client = Client()

    yield client, access_token

    access_token.delete()


def get_api_headers(access_token: AccessToken) -> Dict[str, str]:
    """
    Get API authentication headers for test requests.

    Args:
        access_token: The access token for authentication

    Returns:
        Dictionary with HTTP_AUTHORIZATION header
    """
    return {"HTTP_AUTHORIZATION": f"Bearer {access_token.encoded_token}"}


@pytest.fixture
def guest_api_client(guest_user: AbstractBaseUser) -> Generator[tuple[Client, AccessToken], Any, None]:  # noqa: F811
    """
    Create an authenticated API client for guest user testing.

    Note: Guest users ARE authenticated users with access tokens,
    but they have limited permissions within teams.

    Returns:
        Tuple of (client, access_token) for guest user API testing
    """
    token_str = create_personal_access_token(guest_user)
    access_token = AccessToken.objects.create(
        user=guest_user, encoded_token=token_str, description="Guest Test API Token"
    )

    client = Client()

    yield client, access_token

    access_token.delete()


# ============================================================================
# Team & Billing Fixtures
# ============================================================================


@pytest.fixture
def team_with_community_plan(sample_user: AbstractBaseUser) -> Generator[Team, Any, None]:  # noqa: F811
    """Create a team with community billing plan."""
    # Ensure community plan exists
    community_plan, _ = BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "description": "Free plan for small teams",
            "max_products": 1,
            "max_projects": 1,
            "max_components": 5,
            "max_users": 1,
        },
    )

    team = Team.objects.create(name="Test Community Team", billing_plan=community_plan.key)
    team.key = number_to_random_token(team.pk)
    team.save()

    Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=True)

    yield team

    # Only delete if the team still exists (id is not None)
    if team.id is not None:
        team.delete()


@pytest.fixture
def team_with_business_plan(sample_user: AbstractBaseUser) -> Generator[Team, Any, None]:  # noqa: F811
    """Create a team with business billing plan and trial subscription."""
    # Ensure business plan exists
    business_plan, _ = BillingPlan.objects.get_or_create(
        key="business",
        defaults={
            "name": "Business",
            "description": "For growing teams",
            "max_products": 10,
            "max_projects": 20,
            "max_components": 100,
            "max_users": 10,
            "stripe_product_id": "prod_test_business",
            "stripe_price_monthly_id": "price_test_business_monthly",
            "stripe_price_annual_id": "price_test_business_annual",
        },
    )

    team = Team.objects.create(
        name="Test Business Team",
        billing_plan=business_plan.key,
        billing_plan_limits={
            "max_products": business_plan.max_products,
            "max_projects": business_plan.max_projects,
            "max_components": business_plan.max_components,
            "stripe_customer_id": "cus_test123",
            "stripe_subscription_id": "sub_test123",
            "subscription_status": "active",
        },
    )
    team.key = number_to_random_token(team.pk)
    team.save()

    Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=True)

    yield team

    # Only delete if the team still exists (id is not None)
    if team.id is not None:
        team.delete()


@pytest.fixture
def team_with_enterprise_plan(sample_user: AbstractBaseUser) -> Generator[Team, Any, None]:  # noqa: F811
    """Create a team with enterprise billing plan (unlimited resources)."""
    # Ensure enterprise plan exists
    enterprise_plan, _ = BillingPlan.objects.get_or_create(
        key="enterprise",
        defaults={
            "name": "Enterprise",
            "description": "For large organizations",
            "max_products": None,
            "max_projects": None,
            "max_components": None,
            "max_users": None,
        },
    )

    team = Team.objects.create(name="Test Enterprise Team", billing_plan=enterprise_plan.key)
    team.key = number_to_random_token(team.pk)
    team.save()

    Member.objects.create(team=team, user=sample_user, role="owner", is_default_team=True)

    yield team

    # Only delete if the team still exists (id is not None)
    if team.id is not None:
        team.delete()


# ============================================================================
# Web Client Session Setup Utilities
# ============================================================================


def setup_authenticated_client_session(client: Client, team: Team, user: AbstractBaseUser) -> None:
    """
    Set up an authenticated client session with team context.

    This is a consolidated version of the session setup pattern used across tests.

    Args:
        client: The Django test client
        team: The team to set up session context for
        user: The user to authenticate
    """
    # Ensure team has a valid key
    if not team.key or len(team.key) < 9:
        team.key = number_to_random_token(team.id)
        team.save()

    # Get the member's role
    member = Member.objects.filter(user=user, team=team).first()
    if not member:
        raise ValueError(f"User {user.username} is not a member of team {team.name}")

    # Log in the user
    client.force_login(user)

    # Set up session data with team context
    session = client.session
    session["user_teams"] = {
        team.key: {
            "role": member.role,
            "name": team.name,
            "is_default_team": member.is_default_team,
            "team_id": team.id,
        }
    }
    session["current_team"] = {
        "key": team.key,
        "role": member.role,
        "name": team.name,
        "is_default_team": member.is_default_team,
        "id": team.id,
    }
    session.save()


@pytest.fixture
def authenticated_web_client(
    sample_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
) -> Generator[Client, Any, None]:
    """
    Create an authenticated web client with team session setup.

    Returns:
        Configured Django test client ready for web testing
    """
    client = Client()
    setup_authenticated_client_session(client, team_with_business_plan, sample_user)

    yield client


# ============================================================================
# Multi-User Team Fixtures
# ============================================================================


@pytest.fixture
def team_with_multiple_members(
    sample_user: AbstractBaseUser,  # noqa: F811
    guest_user: AbstractBaseUser,  # noqa: F811
    team_with_business_plan: Team,  # noqa: F811
) -> Generator[Team, Any, None]:
    """
    Create a team with multiple members for testing team functionality.

    Returns:
        Team with owner (sample_user) and guest member (guest_user)
    """
    # Add guest user as a guest member
    Member.objects.create(team=team_with_business_plan, user=guest_user, role="guest")

    yield team_with_business_plan


@pytest.mark.django_db
class AuthenticationTestCase(TestCase):
    @pytest.fixture(autouse=True)
    def setup_user(self, sample_user):  # noqa: F811
        self.user = sample_user

    def setUp(self) -> None:
        if not hasattr(self, "user"):
            raise AttributeError("self.user must be set by pytest fixture")
        if not hasattr(self, "team"):
            raise AttributeError("self.team must be set by pytest fixture")

        self.client.force_login(self.user)
        setup_test_session(self.client, self.team, self.user)


# ============================================================================
# Error Testing Utilities
# ============================================================================


class AuthenticationTestMixin:
    """Mixin class providing common authentication test methods."""

    def assert_requires_authentication(self, client: Client, url: str, method: str = "GET") -> None:
        """Assert that a URL requires authentication."""
        if method.upper() == "GET":
            response = client.get(url)
        elif method.upper() == "POST":
            response = client.post(url)
        elif method.upper() == "PUT":
            response = client.put(url)
        elif method.upper() == "DELETE":
            response = client.delete(url)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        assert response.status_code in [
            401,
            403,
        ], f"Expected 401 Unauthorized or 403 Forbidden, got {response.status_code}"

    def assert_requires_team_permission(self, client: Client, url: str, method: str = "GET") -> None:
        """Assert that a URL requires team permission."""
        if method.upper() == "GET":
            response = client.get(url)
        elif method.upper() == "POST":
            response = client.post(url)
        elif method.upper() == "PUT":
            response = client.put(url)
        elif method.upper() == "DELETE":
            response = client.delete(url)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        assert response.status_code in [
            403,
            404,
        ], f"Expected 403 Forbidden or 404 Not Found, got {response.status_code}"
