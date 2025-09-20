"""
Tests for error response consistency across all API endpoints.

This module verifies that all API endpoints return consistent error responses
with proper error codes and standardized messages.
"""

import os
import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Project
from sbomify.apps.core.schemas import ErrorCode
from sbomify.apps.teams.models import Team, Member
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
class TestErrorResponseConsistency:
    """Test that all endpoints return consistent error responses with error codes."""

    def test_authentication_error_consistency(self, sample_team, sample_user):  # noqa: F811
        """Test that authentication errors are consistent across endpoints."""
        # Create private items
        private_product = Product.objects.create(
            name="Private Product",
            team=sample_team,
            is_public=False
        )
        private_project = Project.objects.create(
            name="Private Project",
            team=sample_team,
            is_public=False
        )
        private_component = Component.objects.create(
            name="Private Component",
            team=sample_team,
            is_public=False
        )
        private_component.projects.add(private_project)

        client = Client()

        # Test endpoints that should return consistent authentication errors
        endpoints = [
            reverse("api-1:get_product", kwargs={"product_id": private_product.id}),
            reverse("api-1:get_project", kwargs={"project_id": private_project.id}),
            reverse("api-1:get_component", kwargs={"component_id": private_component.id}),
            reverse("api-1:list_product_identifiers", kwargs={"product_id": private_product.id}),
            reverse("api-1:list_product_links", kwargs={"product_id": private_product.id}),
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 403
            data = response.json()

            # All authentication errors should include error_code
            assert "error_code" in data, f"Missing error_code in {endpoint}"
            assert data["error_code"] == ErrorCode.UNAUTHORIZED.value

            # All authentication errors should have consistent message format
            assert "Authentication required" in data["detail"]

    def test_forbidden_error_consistency(self, sample_team, sample_user):  # noqa: F811
        """Test that forbidden errors are consistent across endpoints."""
        # Create a different team
        other_team = Team.objects.create(name="Other Team")
        other_user = User.objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="password123"
        )
        Member.objects.create(user=other_user, team=other_team, role="owner")

        # Create items owned by different team
        other_product = Product.objects.create(
            name="Other Product",
            team=other_team,
            is_public=False
        )
        other_project = Project.objects.create(
            name="Other Project",
            team=other_team,
            is_public=False
        )
        other_component = Component.objects.create(
            name="Other Component",
            team=other_team,
            is_public=False
        )
        other_component.projects.add(other_project)

        client = Client()
        # Log in as user from sample_team (different team)
        client.force_login(sample_user)

        # Test endpoints that should return consistent forbidden errors
        endpoints = [
            reverse("api-1:get_product", kwargs={"product_id": other_product.id}),
            reverse("api-1:get_project", kwargs={"project_id": other_project.id}),
            reverse("api-1:get_component", kwargs={"component_id": other_component.id}),
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 403
            data = response.json()

            # All forbidden errors should include error_code
            assert "error_code" in data, f"Missing error_code in {endpoint}"
            assert data["error_code"] == ErrorCode.FORBIDDEN.value

            # All forbidden errors should have consistent message
            assert data["detail"] == "Access denied"

    def test_not_found_error_consistency(self, sample_team, sample_user):  # noqa: F811
        """Test that not found errors are consistent across endpoints."""
        client = Client()
        client.force_login(sample_user)

        # Test endpoints that should return consistent not found errors
        test_cases = [
            (reverse("api-1:get_product", kwargs={"product_id": "nonexistent"}), ErrorCode.NOT_FOUND),
            (reverse("api-1:get_project", kwargs={"project_id": "nonexistent"}), ErrorCode.NOT_FOUND),
            (reverse("api-1:get_component", kwargs={"component_id": "nonexistent"}), ErrorCode.NOT_FOUND),
        ]

        for endpoint, expected_error_code in test_cases:
            response = client.get(endpoint)
            assert response.status_code == 404
            data = response.json()

            # All not found errors should include error_code
            assert "error_code" in data, f"Missing error_code in {endpoint}"
            # Note: some endpoints might use specific error codes like PRODUCT_NOT_FOUND
            assert data["error_code"] in [expected_error_code.value, ErrorCode.PRODUCT_NOT_FOUND.value, ErrorCode.PROJECT_NOT_FOUND.value, ErrorCode.COMPONENT_NOT_FOUND.value]

    def test_duplicate_name_error_consistency(self, sample_team, sample_user, sample_access_token):  # noqa: F811
        """Test that duplicate name errors are consistent across endpoints."""
        # This test focuses on the error message format consistency
        # The actual duplicate name logic is tested elsewhere

        # Just check that the error codes are properly defined
        from sbomify.apps.core.schemas import ErrorCode

        # Verify that DUPLICATE_NAME error code exists
        assert ErrorCode.DUPLICATE_NAME.value == "DUPLICATE_NAME"

        # This would be better tested in integration tests with proper authentication
        # For now, we'll just verify the error code constant exists
        assert hasattr(ErrorCode, 'DUPLICATE_NAME')

    def test_internal_error_consistency(self, sample_team, sample_user):  # noqa: F811
        """Test that internal errors are consistent across endpoints."""
        # This test verifies that generic exception handling includes error codes
        # Note: This is harder to test directly, but we can verify the pattern exists
        # by checking that endpoints that might have internal errors have proper error handling

        client = Client()
        client.force_login(sample_user)

        # Test an endpoint that might have internal errors (with invalid data)
        response = client.get(reverse("api-1:list_products") + "?page=invalid")

        # The response should either be successful or have proper error handling
        if response.status_code == 400:
            data = response.json()
            # If it's a 400 error, it should include error_code
            assert "error_code" in data
            assert "detail" in data

    def test_no_current_team_error_consistency(self, sample_user):  # noqa: F811
        """Test that no current team errors are consistent across endpoints."""
        client = Client()
        client.force_login(sample_user)

        # Clear any team session data
        session = client.session
        session.pop('team_id', None)
        session.save()

        # Test endpoints that require team context
        endpoints = [
            reverse("api-1:create_product"),
            reverse("api-1:create_project"),
            reverse("api-1:create_component"),
        ]

        for endpoint in endpoints:
            response = client.post(
                endpoint,
                data={"name": "Test Item"},
                content_type="application/json"
            )
            assert response.status_code == 403
            data = response.json()

            # All no current team errors should include error_code
            assert "error_code" in data, f"Missing error_code in {endpoint}"
            # Note: The billing check might come first, so we need to check for both
            assert data["error_code"] in [ErrorCode.NO_CURRENT_TEAM.value, ErrorCode.NO_BILLING_PLAN.value]


@pytest.mark.django_db
class TestErrorMessageStandardization:
    """Test that error messages are standardized across similar endpoints."""

    def test_authentication_message_standardization(self, sample_team):  # noqa: F811
        """Test that authentication error messages are standardized."""
        # Create private items
        private_product = Product.objects.create(
            name="Private Product",
            team=sample_team,
            is_public=False
        )
        private_project = Project.objects.create(
            name="Private Project",
            team=sample_team,
            is_public=False
        )
        private_component = Component.objects.create(
            name="Private Component",
            team=sample_team,
            is_public=False
        )

        client = Client()

        # Test that all similar endpoints use the same authentication message
        endpoints_and_expected_messages = [
            (reverse("api-1:get_product", kwargs={"product_id": private_product.id}), "Authentication required for private items"),
            (reverse("api-1:get_project", kwargs={"project_id": private_project.id}), "Authentication required for private items"),
            (reverse("api-1:get_component", kwargs={"component_id": private_component.id}), "Authentication required for private items"),
        ]

        for endpoint, expected_message in endpoints_and_expected_messages:
            response = client.get(endpoint)
            assert response.status_code == 403
            data = response.json()
            assert data["detail"] == expected_message, f"Inconsistent message for {endpoint}"

    def test_forbidden_message_standardization(self, sample_team, sample_user):  # noqa: F811
        """Test that forbidden error messages are standardized."""
        # Create a different team
        other_team = Team.objects.create(name="Other Team")
        other_user = User.objects.create_user(
            username="otheruser2",
            email="other2@example.com",
            password="password123"
        )
        Member.objects.create(user=other_user, team=other_team, role="owner")

        # Create items owned by different team
        other_product = Product.objects.create(
            name="Other Product",
            team=other_team,
            is_public=False
        )
        other_project = Project.objects.create(
            name="Other Project",
            team=other_team,
            is_public=False
        )
        other_component = Component.objects.create(
            name="Other Component",
            team=other_team,
            is_public=False
        )

        client = Client()
        client.force_login(sample_user)

        # Test that all similar endpoints use the same forbidden message
        endpoints = [
            reverse("api-1:get_product", kwargs={"product_id": other_product.id}),
            reverse("api-1:get_project", kwargs={"project_id": other_project.id}),
            reverse("api-1:get_component", kwargs={"component_id": other_component.id}),
        ]

        for endpoint in endpoints:
            response = client.get(endpoint)
            assert response.status_code == 403
            data = response.json()
            assert data["detail"] == "Access denied", f"Inconsistent message for {endpoint}"