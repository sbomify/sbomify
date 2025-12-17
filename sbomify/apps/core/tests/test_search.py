"""Tests for search functionality."""

import json

import pytest
from django.contrib.auth.base_user import AbstractBaseUser
from django.test import Client
from django.urls import reverse

from sbomify.apps.core.models import Component, Product, Project
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401


@pytest.mark.django_db
class TestSearchView:
    """Test cases for SearchView."""

    def test_search_requires_authentication(self, client: Client):
        """Test that search endpoint requires authentication."""
        response = client.get(reverse("core:search"), {"q": "test"})
        assert response.status_code == 302

    def test_search_empty_query_returns_empty_results(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that empty query returns empty results."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        response = client.get(reverse("core:search"), {"q": ""})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["products"] == []
        assert data["projects"] == []
        assert data["components"] == []

    def test_search_short_query_returns_empty_results(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that query shorter than 2 characters returns empty results."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        response = client.get(reverse("core:search"), {"q": "a"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["products"] == []
        assert data["projects"] == []
        assert data["components"] == []

    def test_search_products(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test searching for products."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        Product.objects.create(
            name="Test Product",
            description="A test product description",
            team=team,
        )
        Product.objects.create(
            name="Another Product",
            description="Different product",
            team=team,
        )

        response = client.get(reverse("core:search"), {"q": "Test"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) == 1
        assert data["products"][0]["name"] == "Test Product"
        assert "test product description" in data["products"][0]["description"].lower()

    def test_search_projects(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test searching for projects."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        Project.objects.create(name="Test Project", team=team)
        Project.objects.create(name="Another Project", team=team)

        response = client.get(reverse("core:search"), {"q": "Test"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["projects"]) == 1
        assert data["projects"][0]["name"] == "Test Project"

    def test_search_components(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test searching for components."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        Component.objects.create(
            name="Test Component",
            team=team,
            component_type=Component.ComponentType.SBOM,
        )
        Component.objects.create(
            name="Another Component",
            team=team,
            component_type=Component.ComponentType.DOCUMENT,
        )

        response = client.get(reverse("core:search"), {"q": "Test"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["components"]) == 1
        assert data["components"][0]["name"] == "Test Component"
        assert data["components"][0]["component_type"] == "sbom"

    def test_search_respects_team_scope(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that search only returns results from current team."""
        from sbomify.apps.teams.models import Member, Team

        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        other_team = Team.objects.create(name="Other Team")
        Member.objects.create(team=other_team, user=user, role="owner")

        Product.objects.create(name="Team Product", team=team)
        Product.objects.create(name="Other Team Product", team=other_team)

        response = client.get(reverse("core:search"), {"q": "Product"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) == 1
        assert data["products"][0]["name"] == "Team Product"

    def test_search_limit_parameter(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that limit parameter works correctly."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        for i in range(15):
            Product.objects.create(name=f"Product {i}", team=team)

        response = client.get(reverse("core:search"), {"q": "Product", "limit": 5})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) == 5

    def test_search_limit_validation_max(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that limit is capped at maximum value."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        for i in range(100):
            Product.objects.create(name=f"Product {i}", team=team)

        response = client.get(reverse("core:search"), {"q": "Product", "limit": 1000})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) <= 50

    def test_search_limit_validation_min(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that limit is enforced at minimum value."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        Product.objects.create(name="Product 1", team=team)
        Product.objects.create(name="Product 2", team=team)

        response = client.get(reverse("core:search"), {"q": "Product", "limit": 0})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) >= 1

    def test_search_limit_invalid_type(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that invalid limit type defaults to 10."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        for i in range(15):
            Product.objects.create(name=f"Product {i}", team=team)

        response = client.get(reverse("core:search"), {"q": "Product", "limit": "invalid"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) == 10

    def test_search_case_insensitive(
        self, client: Client, sample_team_with_owner_member
    ):
        """Test that search is case insensitive."""
        team = sample_team_with_owner_member.team
        user = sample_team_with_owner_member.user
        setup_authenticated_client_session(client, team, user)

        Product.objects.create(name="Test Product", team=team)

        response = client.get(reverse("core:search"), {"q": "test"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) == 1

        response = client.get(reverse("core:search"), {"q": "TEST"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert len(data["products"]) == 1

    def test_search_no_team_returns_empty(
        self, client: Client, sample_user: AbstractBaseUser
    ):
        """Test that search without team returns empty results."""
        client.force_login(sample_user)

        response = client.get(reverse("core:search"), {"q": "test"})
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data["products"] == []
        assert data["projects"] == []
        assert data["components"] == []

