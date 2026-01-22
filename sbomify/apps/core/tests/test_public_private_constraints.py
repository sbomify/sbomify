"""Tests for public/private constraint validation in the API."""

import json
from django.test import Client
from django.urls import reverse
import pytest

from sbomify.apps.core.apis import _private_items_allowed
from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401
from sbomify.apps.sboms.models import Component, Product, Project
from sbomify.apps.sboms.tests.test_views import setup_test_session


@pytest.mark.django_db
class TestPublicPrivateConstraints:
    """Test public/private constraint validation."""

    def setup_method(self):
        """Set up test data."""
        self.client = Client()


@pytest.mark.django_db
def test_private_items_invalid_plan_treated_as_public(sample_team_with_owner_member):
    """Invalid billing plans should not 500 core APIs; treat as public-only."""
    team = sample_team_with_owner_member.team
    team.billing_plan = "invalid_plan"
    team.save()

    assert _private_items_allowed(team) is False


@pytest.mark.django_db
def test_can_make_project_public_with_private_components(
    sample_team_with_owner_member, sample_user  # noqa: F811
):
    """Test that making a project public succeeds even if it has private components.
    
    Private components will simply not appear in public views.
    """
    client = Client()
    team = sample_team_with_owner_member.team

    BillingPlan.objects.create(key="test_plan", name="Test Plan", max_components=10, max_products=10, max_projects=10)
    team.billing_plan = "test_plan"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    project = Project.objects.create(name="Test Project", team=team, is_public=False)
    component = Component.objects.create(name="Test Component", team=team, visibility=Component.Visibility.PRIVATE)
    project.components.add(component)

    url = reverse("api-1:patch_project", kwargs={"project_id": project.id})
    response = client.patch(url, json.dumps({"is_public": True}), content_type="application/json")

    assert response.status_code == 200
    project.refresh_from_db()
    assert project.is_public is True
    assert component.visibility == Component.Visibility.PRIVATE  # Component remains private


@pytest.mark.django_db
def test_can_assign_private_component_to_public_project(
    sample_team_with_owner_member, sample_user  # noqa: F811
):
    """Test that assigning a private component to a public project succeeds.
    
    Private components will simply not appear in public views.
    """
    client = Client()
    team = sample_team_with_owner_member.team

    BillingPlan.objects.create(key="test_plan", name="Test Plan", max_components=10, max_products=10, max_projects=10)
    team.billing_plan = "test_plan"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    project = Project.objects.create(name="Test Project", team=team, is_public=True)
    component = Component.objects.create(name="Test Component", team=team, visibility=Component.Visibility.PRIVATE)

    url = reverse("api-1:patch_project", kwargs={"project_id": project.id})
    response = client.patch(url, json.dumps({"component_ids": [component.id]}), content_type="application/json")

    assert response.status_code == 200
    assert component in project.components.all()
    assert component.visibility == Component.Visibility.PRIVATE  # Component remains private


@pytest.mark.django_db
def test_can_make_component_private_when_assigned_to_public_project(
    sample_team_with_owner_member, sample_user  # noqa: F811
):
    """Test that making a component private succeeds even if it's assigned to public projects.
    
    The component will simply not appear in public views.
    """
    client = Client()
    team = sample_team_with_owner_member.team

    BillingPlan.objects.create(key="test_plan", name="Test Plan", max_components=10, max_products=10, max_projects=10)
    team.billing_plan = "test_plan"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    project = Project.objects.create(name="Test Project", team=team, is_public=True)
    component = Component.objects.create(name="Test Component", team=team, visibility=Component.Visibility.PUBLIC)
    project.components.add(component)

    url = reverse("api-1:patch_component", kwargs={"component_id": component.id})
    response = client.patch(url, json.dumps({"visibility": "private"}), content_type="application/json")

    assert response.status_code == 200
    component.refresh_from_db()
    assert component.visibility == Component.Visibility.PRIVATE
    assert component in project.components.all()  # Still assigned to project


@pytest.mark.django_db
def test_can_make_product_public_with_private_projects(
    sample_team_with_owner_member, sample_user  # noqa: F811
):
    """Test that making a product public succeeds even if it has private projects.
    
    Private projects will simply not appear in public views.
    """
    client = Client()
    team = sample_team_with_owner_member.team

    BillingPlan.objects.create(key="test_plan", name="Test Plan", max_components=10, max_products=10, max_projects=10)
    team.billing_plan = "test_plan"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    product = Product.objects.create(name="Test Product", team=team, is_public=False)
    project = Project.objects.create(name="Test Project", team=team, is_public=False)
    product.projects.add(project)

    url = reverse("api-1:patch_product", kwargs={"product_id": product.id})
    response = client.patch(url, json.dumps({"is_public": True}), content_type="application/json")

    assert response.status_code == 200
    product.refresh_from_db()
    assert product.is_public is True
    assert project.is_public is False  # Project remains private


@pytest.mark.django_db
def test_cannot_make_project_private_when_assigned_to_public_product(
    sample_team_with_owner_member, sample_user  # noqa: F811
):
    """Test that making a project private fails if it's assigned to public products."""
    client = Client()
    team = sample_team_with_owner_member.team

    BillingPlan.objects.create(
        key="test_plan",
        name="Test Plan",
        max_components=10,
        max_products=10,
        max_projects=10,
    )
    team.billing_plan = "test_plan"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    product = Product.objects.create(name="Test Product", team=team, is_public=True)
    project = Project.objects.create(name="Test Project", team=team, is_public=True)
    product.projects.add(project)

    url = reverse("api-1:patch_project", kwargs={"project_id": project.id})
    response = client.patch(url, json.dumps({"is_public": False}), content_type="application/json")

    assert response.status_code == 400
    assert "Cannot make project private because it's assigned to public products" in response.json()["detail"]
    assert "Test Product" in response.json()["detail"]


@pytest.mark.django_db
def test_community_plan_rejects_private_product(sample_team_with_owner_member, sample_user):  # noqa: F811
    """Community plan users cannot set products private."""
    client = Client()
    team = sample_team_with_owner_member.team
    team.billing_plan = "community"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    product = Product.objects.create(name="Community Product", team=team, is_public=True)
    url = reverse("api-1:patch_product", kwargs={"product_id": product.id})
    response = client.patch(url, json.dumps({"is_public": False}), content_type="application/json")

    assert response.status_code == 403
    assert "cannot make items private" in response.json()["detail"]


@pytest.mark.django_db
def test_community_plan_rejects_private_project(sample_team_with_owner_member, sample_user):  # noqa: F811
    """Community plan users cannot set projects private."""
    client = Client()
    team = sample_team_with_owner_member.team
    team.billing_plan = "community"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    project = Project.objects.create(name="Community Project", team=team, is_public=True)
    url = reverse("api-1:patch_project", kwargs={"project_id": project.id})
    response = client.patch(url, json.dumps({"is_public": False}), content_type="application/json")

    assert response.status_code == 403
    assert "cannot make items private" in response.json()["detail"]


@pytest.mark.django_db
def test_community_plan_rejects_private_component(sample_team_with_owner_member, sample_user):  # noqa: F811
    """Community plan users cannot set components private."""
    client = Client()
    team = sample_team_with_owner_member.team
    team.billing_plan = "community"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    component = Component.objects.create(name="Community Component", team=team, visibility=Component.Visibility.PUBLIC)
    url = reverse("api-1:patch_component", kwargs={"component_id": component.id})
    response = client.patch(url, json.dumps({"visibility": "private"}), content_type="application/json")

    assert response.status_code == 403
    assert "cannot make items private" in response.json()["detail"]


@pytest.mark.django_db
def test_community_plan_put_update_product_requires_explicit_public_flag(
    sample_team_with_owner_member, sample_user  # noqa: F811
):
    """Community plan can update products when explicitly keeping them public."""
    client = Client()
    team = sample_team_with_owner_member.team
    team.billing_plan = "community"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    product = Product.objects.create(name="Community Product", team=team, is_public=True, description="orig")

    url = reverse("api-1:update_product", kwargs={"product_id": product.id})
    response = client.put(
        url,
        json.dumps({"name": "Updated Product", "description": "orig", "is_public": True}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["is_public"] is True


@pytest.mark.django_db
def test_community_plan_put_update_project_allows_public(
    sample_team_with_owner_member, sample_user  # noqa: F811
):
    """Community plan can update projects (is_public=True required)."""
    client = Client()
    team = sample_team_with_owner_member.team
    team.billing_plan = "community"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    project = Project.objects.create(name="Community Project", team=team, is_public=True, metadata={"a": 1})

    url = reverse("api-1:update_project", kwargs={"project_id": project.id})
    response = client.put(
        url,
        json.dumps({"name": "Updated Project", "metadata": {"a": 1}, "is_public": True}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["is_public"] is True


@pytest.mark.django_db
def test_community_plan_put_update_component_allows_public(
    sample_team_with_owner_member, sample_user  # noqa: F811
):
    """Community plan can update components (is_public=True required)."""
    client = Client()
    team = sample_team_with_owner_member.team
    team.billing_plan = "community"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    component = Component.objects.create(name="Community Component", team=team, visibility=Component.Visibility.PUBLIC)

    url = reverse("api-1:update_component", kwargs={"component_id": component.id})
    response = client.put(
        url,
        json.dumps(
            {
                "name": "Updated Component",
                "component_type": component.component_type,
                "metadata": {},
                "is_global": False,
                "visibility": "public",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["visibility"] == "public"


@pytest.mark.django_db
def test_community_plan_put_cannot_make_product_private(sample_team_with_owner_member, sample_user):  # noqa: F811
    """Community plan cannot flip product to private via PUT."""
    client = Client()
    team = sample_team_with_owner_member.team
    team.billing_plan = "community"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    product = Product.objects.create(name="Community Product", team=team, is_public=True, description="orig")

    url = reverse("api-1:update_product", kwargs={"product_id": product.id})
    response = client.put(
        url,
        json.dumps({"name": "Updated Product", "description": "orig", "is_public": False}),
        content_type="application/json",
    )

    assert response.status_code == 403
    assert "cannot make items private" in response.json()["detail"]


@pytest.mark.django_db
def test_community_plan_put_cannot_make_project_private(sample_team_with_owner_member, sample_user):  # noqa: F811
    """Community plan cannot flip project to private via PUT."""
    client = Client()
    team = sample_team_with_owner_member.team
    team.billing_plan = "community"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    project = Project.objects.create(name="Community Project", team=team, is_public=True, metadata={"a": 1})

    url = reverse("api-1:update_project", kwargs={"project_id": project.id})
    response = client.put(
        url,
        json.dumps({"name": "Updated Project", "metadata": {"a": 1}, "is_public": False}),
        content_type="application/json",
    )

    assert response.status_code == 403
    assert "cannot make items private" in response.json()["detail"]


@pytest.mark.django_db
def test_community_plan_put_cannot_make_component_private(sample_team_with_owner_member, sample_user):  # noqa: F811
    """Community plan cannot flip component to private via PUT."""
    client = Client()
    team = sample_team_with_owner_member.team
    team.billing_plan = "community"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    component = Component.objects.create(name="Community Component", team=team, visibility=Component.Visibility.PUBLIC)

    url = reverse("api-1:update_component", kwargs={"component_id": component.id})
    response = client.put(
        url,
        json.dumps(
            {
                "name": "Updated Component",
                "component_type": component.component_type,
                "metadata": {},
                "is_global": False,
                "visibility": "private",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 403
    assert "cannot make items private" in response.json()["detail"]


@pytest.mark.django_db
def test_cannot_make_public_project_private_when_assigned_to_public_product(
    sample_team_with_owner_member, sample_user  # noqa: F811
):
    """Test the exact edge case: public product + public project -> cannot make project private."""
    client = Client()
    team = sample_team_with_owner_member.team

    BillingPlan.objects.create(
        key="test_plan",
        name="Test Plan",
        max_components=10,
        max_products=10,
        max_projects=10,
    )
    team.billing_plan = "test_plan"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    product = Product.objects.create(name="Test Product", team=team, is_public=True)
    project = Project.objects.create(name="Test Project", team=team, is_public=True)
    product.projects.add(project)

    url = reverse("api-1:patch_project", kwargs={"project_id": project.id})
    response = client.patch(url, json.dumps({"is_public": False}), content_type="application/json")

    assert response.status_code == 400
    assert "Cannot make project private because it's assigned to public products" in response.json()["detail"]
    assert "Test Product" in response.json()["detail"]

    project.refresh_from_db()
    assert project.is_public is True


@pytest.mark.django_db
def test_toggle_endpoint_cannot_make_public_project_private_when_assigned_to_public_product(
    sample_team_with_owner_member, sample_user  # noqa: F811
):
    """Test that the toggle endpoint (used by UI) properly validates constraints."""
    client = Client()
    team = sample_team_with_owner_member.team

    BillingPlan.objects.create(
        key="test_plan",
        name="Test Plan",
        max_components=10,
        max_products=10,
        max_projects=10,
    )
    team.billing_plan = "test_plan"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    product = Product.objects.create(name="Test Product", team=team, is_public=True)
    project = Project.objects.create(name="Test Project", team=team, is_public=True)
    product.projects.add(project)

    url = reverse("api-1:patch_project", kwargs={"project_id": project.id})
    response = client.patch(url, json.dumps({"is_public": False}), content_type="application/json")

    assert response.status_code == 400
    assert "Cannot make project private because it's assigned to public products" in response.json()["detail"]
    assert "Test Product" in response.json()["detail"]

    project.refresh_from_db()
    assert project.is_public is True


@pytest.mark.django_db
def test_valid_operations_are_allowed(sample_team_with_owner_member, sample_user):  # noqa: F811
    """Test that valid operations are still allowed."""
    client = Client()
    team = sample_team_with_owner_member.team

    BillingPlan.objects.create(
        key="test_plan",
        name="Test Plan",
        max_components=10,
        max_products=10,
        max_projects=10,
    )
    team.billing_plan = "test_plan"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    project = Project.objects.create(name="Test Project", team=team, is_public=False)
    component = Component.objects.create(name="Test Component", team=team, visibility=Component.Visibility.PUBLIC)
    project.components.add(component)

    url = reverse("api-1:patch_project", kwargs={"project_id": project.id})
    response = client.patch(url, json.dumps({"is_public": True}), content_type="application/json")

    assert response.status_code == 200
    assert response.json()["is_public"] is True

    response = client.patch(url, json.dumps({"is_public": False}), content_type="application/json")
    assert response.status_code == 200

    component_url = reverse("api-1:patch_component", kwargs={"component_id": component.id})
    response = client.patch(
        component_url, json.dumps({"visibility": "private"}), content_type="application/json"
    )

    assert response.status_code == 200
    assert response.json()["visibility"] == "private"


@pytest.mark.django_db
def test_private_projects_hidden_in_public_product_view(sample_team_with_owner_member):
    """Test that private projects don't appear in public views of a public product."""
    team = sample_team_with_owner_member.team
    team.is_public = True
    team.save()

    # Create public product with both public and private projects
    product = Product.objects.create(name="Public Product", team=team, is_public=True)
    public_project = Project.objects.create(name="Public Project", team=team, is_public=True)
    private_project = Project.objects.create(name="Private Project", team=team, is_public=False)
    
    product.projects.add(public_project, private_project)

    # Import view helpers
    from sbomify.apps.core.views.product_details_public import _prepare_public_projects_with_components

    # Get public projects - should only include public project
    public_projects = _prepare_public_projects_with_components(product.id, is_custom_domain=False)
    
    project_names = [p["name"] for p in public_projects]
    assert "Public Project" in project_names
    assert "Private Project" not in project_names


@pytest.mark.django_db
def test_private_components_hidden_in_public_project_view(sample_team_with_owner_member):
    """Test that private components don't appear in public views of a public project."""
    team = sample_team_with_owner_member.team
    team.is_public = True
    team.save()

    # Create public project with both public and private components
    project = Project.objects.create(name="Public Project", team=team, is_public=True)
    public_component = Component.objects.create(name="Public Component", team=team, visibility=Component.Visibility.PUBLIC)
    private_component = Component.objects.create(name="Private Component", team=team, visibility=Component.Visibility.PRIVATE)
    
    project.components.add(public_component, private_component)

    # Import view helpers
    from sbomify.apps.core.views.project_details_public import _prepare_public_components

    # Get public components - should only include public component
    public_components = _prepare_public_components(project, is_custom_domain=False)
    
    component_names = [c["name"] for c in public_components]
    assert "Public Component" in component_names
    assert "Private Component" not in component_names


@pytest.mark.django_db
def test_workspace_public_view_filters_private_items(sample_team_with_owner_member):
    """Test that workspace public view only shows products with public projects."""
    team = sample_team_with_owner_member.team
    team.is_public = True
    team.save()

    # Create products with different visibility scenarios
    # 1. Public product with public project - SHOULD SHOW
    product1 = Product.objects.create(name="Product with Public Project", team=team, is_public=True)
    public_project = Project.objects.create(name="Public Project", team=team, is_public=True)
    product1.projects.add(public_project)

    # 2. Public product with only private projects - SHOULD NOT SHOW
    product2 = Product.objects.create(name="Product with Only Private Projects", team=team, is_public=True)
    private_project = Project.objects.create(name="Private Project", team=team, is_public=False)
    product2.projects.add(private_project)

    # 3. Private product - SHOULD NOT SHOW
    Product.objects.create(name="Private Product", team=team, is_public=False)

    # Import view helpers
    from sbomify.apps.core.views.workspace_public import _list_public_products

    # Get public products
    public_products = _list_public_products(team)
    
    product_names = [p["name"] for p in public_products]
    assert "Product with Public Project" in product_names
    assert "Product with Only Private Projects" not in product_names
    assert "Private Product" not in product_names

