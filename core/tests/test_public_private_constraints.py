"""Tests for public/private constraint validation in the API."""

import json
from django.test import Client
from django.urls import reverse
import pytest

from billing.models import BillingPlan
from core.tests.fixtures import sample_user  # noqa: F401
from teams.fixtures import sample_team_with_owner_member  # noqa: F401
from sboms.models import Component, Product, Project
from sboms.tests.test_views import setup_test_session


@pytest.mark.django_db
class TestPublicPrivateConstraints:
    """Test public/private constraint validation."""

    def setup_method(self):
        """Set up test data."""
        self.client = Client()

    def test_cannot_make_project_public_with_private_components(
        self, sample_team_with_owner_member, sample_user  # noqa: F811
    ):
        """Test that making a project public fails if it has private components."""
        team = sample_team_with_owner_member.team

        # Create billing plan
        BillingPlan.objects.create(
            key="test_plan",
            name="Test Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "test_plan"
        team.save()

        # Set up authentication and session
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, team.members.first())

        # Create a private project and private component
        project = Project.objects.create(
            name="Test Project",
            team=team,
            is_public=False
        )
        component = Component.objects.create(
            name="Test Component",
            team=team,
            is_public=False
        )

        # Assign component to project
        project.components.add(component)

        # Try to make project public - should fail
        url = reverse("api-1:patch_project", kwargs={"project_id": project.id})
        response = self.client.patch(
            url,
            json.dumps({"is_public": True}),
            content_type="application/json"
        )

        assert response.status_code == 400
        assert "Cannot make project public because it contains private components" in response.json()["detail"]
        assert "Test Component" in response.json()["detail"]

    def test_cannot_assign_private_component_to_public_project(
        self, sample_team_with_owner_member, sample_user  # noqa: F811
    ):
        """Test that assigning a private component to a public project fails."""
        team = sample_team_with_owner_member.team

        # Create billing plan
        BillingPlan.objects.create(
            key="test_plan",
            name="Test Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "test_plan"
        team.save()

        # Set up authentication and session
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, team.members.first())

        # Create a public project and private component
        project = Project.objects.create(
            name="Test Project",
            team=team,
            is_public=True
        )
        component = Component.objects.create(
            name="Test Component",
            team=team,
            is_public=False
        )

        # Try to assign private component to public project - should fail
        url = reverse("api-1:patch_project", kwargs={"project_id": project.id})
        response = self.client.patch(
            url,
            json.dumps({"component_ids": [component.id]}),
            content_type="application/json"
        )

        assert response.status_code == 400
        assert "Cannot assign private components to a public project" in response.json()["detail"]
        assert "Test Component" in response.json()["detail"]

    def test_cannot_make_component_private_when_assigned_to_public_project(
        self, sample_team_with_owner_member, sample_user  # noqa: F811
    ):
        """Test that making a component private fails if it's assigned to public projects."""
        team = sample_team_with_owner_member.team

        # Create billing plan
        BillingPlan.objects.create(
            key="test_plan",
            name="Test Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "test_plan"
        team.save()

        # Set up authentication and session
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, team.members.first())

        # Create a public project and public component
        project = Project.objects.create(
            name="Test Project",
            team=team,
            is_public=True
        )
        component = Component.objects.create(
            name="Test Component",
            team=team,
            is_public=True
        )

        # Assign component to project
        project.components.add(component)

        # Try to make component private - should fail
        url = reverse("api-1:patch_component", kwargs={"component_id": component.id})
        response = self.client.patch(
            url,
            json.dumps({"is_public": False}),
            content_type="application/json"
        )

        assert response.status_code == 400
        assert "Cannot make component private because it's assigned to public projects" in response.json()["detail"]
        assert "Test Project" in response.json()["detail"]

    def test_cannot_make_product_public_with_private_projects(
        self, sample_team_with_owner_member, sample_user  # noqa: F811
    ):
        """Test that making a product public fails if it has private projects."""
        team = sample_team_with_owner_member.team

        # Create billing plan
        BillingPlan.objects.create(
            key="test_plan",
            name="Test Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "test_plan"
        team.save()

        # Set up authentication and session
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, team.members.first())

        # Create a private product and private project
        product = Product.objects.create(
            name="Test Product",
            team=team,
            is_public=False
        )
        project = Project.objects.create(
            name="Test Project",
            team=team,
            is_public=False
        )

        # Assign project to product
        product.projects.add(project)

        # Try to make product public - should fail
        url = reverse("api-1:patch_product", kwargs={"product_id": product.id})
        response = self.client.patch(
            url,
            json.dumps({"is_public": True}),
            content_type="application/json"
        )

        assert response.status_code == 400
        assert "Cannot make product public because it contains private projects" in response.json()["detail"]
        assert "Test Project" in response.json()["detail"]

    def test_cannot_make_project_private_when_assigned_to_public_product(
        self, sample_team_with_owner_member, sample_user  # noqa: F811
    ):
        """Test that making a project private fails if it's assigned to public products."""
        team = sample_team_with_owner_member.team

        # Create billing plan
        BillingPlan.objects.create(
            key="test_plan",
            name="Test Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "test_plan"
        team.save()

        # Set up authentication and session
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, team.members.first())

        # Create a public product and public project
        product = Product.objects.create(
            name="Test Product",
            team=team,
            is_public=True
        )
        project = Project.objects.create(
            name="Test Project",
            team=team,
            is_public=True
        )

        # Assign project to product
        product.projects.add(project)

        # Try to make project private - should fail
        url = reverse("api-1:patch_project", kwargs={"project_id": project.id})
        response = self.client.patch(
            url,
            json.dumps({"is_public": False}),
            content_type="application/json"
        )

        assert response.status_code == 400
        assert "Cannot make project private because it's assigned to public products" in response.json()["detail"]
        assert "Test Product" in response.json()["detail"]

    def test_cannot_make_public_project_private_when_assigned_to_public_product(
        self, sample_team_with_owner_member, sample_user  # noqa: F811
    ):
        """Test the exact edge case: public product + public project -> cannot make project private."""
        team = sample_team_with_owner_member.team

        # Create billing plan
        BillingPlan.objects.create(
            key="test_plan",
            name="Test Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "test_plan"
        team.save()

        # Set up authentication and session
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, team.members.first())

        # Step 1: Create a public product and public project
        product = Product.objects.create(
            name="Test Product",
            team=team,
            is_public=True
        )
        project = Project.objects.create(
            name="Test Project",
            team=team,
            is_public=True
        )

        # Step 2: Assign the project to the product
        product.projects.add(project)

        # Step 3: Try to make the project private - this should FAIL
        url = reverse("api-1:patch_project", kwargs={"project_id": project.id})
        response = self.client.patch(
            url,
            json.dumps({"is_public": False}),
            content_type="application/json"
        )

        assert response.status_code == 400
        assert "Cannot make project private because it's assigned to public products" in response.json()["detail"]
        assert "Test Product" in response.json()["detail"]

        # Verify the project is still public
        project.refresh_from_db()
        assert project.is_public is True

    def test_toggle_endpoint_cannot_make_public_project_private_when_assigned_to_public_product(
        self, sample_team_with_owner_member, sample_user  # noqa: F811
    ):
        """Test that the toggle endpoint (used by UI) properly validates constraints."""
        team = sample_team_with_owner_member.team

        # Create billing plan
        BillingPlan.objects.create(
            key="test_plan",
            name="Test Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "test_plan"
        team.save()

        # Set up authentication and session
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, team.members.first())

        # Step 1: Create a public product and public project
        product = Product.objects.create(
            name="Test Product",
            team=team,
            is_public=True
        )
        project = Project.objects.create(
            name="Test Project",
            team=team,
            is_public=True
        )

        # Step 2: Assign the project to the product
        product.projects.add(project)

        # Step 3: Try to make the project private using the core API (which the updated toggle component uses) - this should FAIL
        url = reverse("api-1:patch_project", kwargs={"project_id": project.id})
        response = self.client.patch(
            url,
            json.dumps({"is_public": False}),
            content_type="application/json"
        )

        assert response.status_code == 400
        assert "Cannot make project private because it's assigned to public products" in response.json()["detail"]
        assert "Test Product" in response.json()["detail"]

        # Verify the project is still public
        project.refresh_from_db()
        assert project.is_public is True

    def test_valid_operations_are_allowed(
        self, sample_team_with_owner_member, sample_user  # noqa: F811
    ):
        """Test that valid operations are still allowed."""
        team = sample_team_with_owner_member.team

        # Create billing plan
        BillingPlan.objects.create(
            key="test_plan",
            name="Test Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "test_plan"
        team.save()

        # Set up authentication and session
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, team.members.first())

        # Create a project with public components
        project = Project.objects.create(
            name="Test Project",
            team=team,
            is_public=False
        )
        component = Component.objects.create(
            name="Test Component",
            team=team,
            is_public=True
        )

        # Assign component to project
        project.components.add(component)

        # Making project public should work when all components are public
        url = reverse("api-1:patch_project", kwargs={"project_id": project.id})
        response = self.client.patch(
            url,
            json.dumps({"is_public": True}),
            content_type="application/json"
        )

        assert response.status_code == 200
        assert response.json()["is_public"] is True

        # Making component private should work when project is not public (after making it private first)
        response = self.client.patch(
            url,
            json.dumps({"is_public": False}),
            content_type="application/json"
        )
        assert response.status_code == 200

        component_url = reverse("api-1:patch_component", kwargs={"component_id": component.id})
        response = self.client.patch(
            component_url,
            json.dumps({"is_public": False}),
            content_type="application/json"
        )

        assert response.status_code == 200
        assert response.json()["is_public"] is False