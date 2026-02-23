"""Tests for GDPR data export."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Member, Team

User = get_user_model()


@pytest.fixture
def export_user(db):
    """Create a user for export tests."""
    return User.objects.create_user(
        username="exportuser",
        email="export@example.com",
        first_name="Export",
        last_name="User",
    )


@pytest.fixture
def export_team(export_user, db):
    """Create a team for the export user."""
    BillingPlan.objects.get_or_create(
        key="community",
        defaults={
            "name": "Community",
            "description": "Free plan",
            "max_products": 1,
            "max_projects": 1,
            "max_components": 5,
            "max_users": 2,
        },
    )
    team = Team.objects.create(name="Export Team", billing_plan="community")
    team.key = number_to_random_token(team.pk)
    team.save()
    Member.objects.create(team=team, user=export_user, role="owner", is_default_team=True)
    return team


class TestDataExportAPI:
    @pytest.mark.django_db
    def test_export_returns_user_profile(self, export_user, export_team):
        """Export includes user profile data."""
        client = Client()
        client.force_login(export_user)
        setup_authenticated_client_session(client, export_team, export_user)

        response = client.get("/api/v1/user/export")

        assert response.status_code == 200
        data = response.json()
        assert data["user"]["email"] == export_user.email
        assert data["user"]["username"] == export_user.username
        assert data["export_version"] == "1.0"

    @pytest.mark.django_db
    def test_export_includes_workspaces(self, export_user, export_team):
        """Export includes workspace memberships."""
        client = Client()
        client.force_login(export_user)
        setup_authenticated_client_session(client, export_team, export_user)

        response = client.get("/api/v1/user/export")

        assert response.status_code == 200
        data = response.json()
        assert len(data["workspaces"]) >= 1
        assert data["workspaces"][0]["name"] == export_team.name

    @pytest.mark.django_db
    def test_export_unauthenticated_rejected(self):
        """Unauthenticated export request is rejected."""
        client = Client()
        response = client.get("/api/v1/user/export")
        assert response.status_code == 401

    @pytest.mark.django_db
    def test_export_includes_empty_collections(self, export_user, export_team):
        """Export includes empty collections when user has no artifacts."""
        client = Client()
        client.force_login(export_user)
        setup_authenticated_client_session(client, export_team, export_user)

        response = client.get("/api/v1/user/export")

        data = response.json()
        assert data["sboms"] == []
        assert data["documents"] == []
        assert data["api_tokens"] == []
