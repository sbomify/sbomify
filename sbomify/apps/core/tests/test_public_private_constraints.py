"""Tests for public/private constraint validation in the API."""

import json

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.billing.models import BillingPlan
from sbomify.apps.core.apis import _private_items_allowed
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.sboms.models import Component, Product
from sbomify.apps.sboms.tests.test_views import setup_test_session
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401


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
def test_can_make_product_public_with_private_components(
    sample_team_with_owner_member,
    sample_user,  # noqa: F811
):
    """Test that making a product public succeeds even if it has private components.

    Private components will simply not appear in public views.
    """
    client = Client()
    team = sample_team_with_owner_member.team

    BillingPlan.objects.create(key="test_plan", name="Test Plan", max_components=10, max_products=10)
    team.billing_plan = "test_plan"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    product = Product.objects.create(name="Test Product", team=team, is_public=False)
    component = Component.objects.create(
        name="Private Component", team=team, visibility=Component.Visibility.PRIVATE
    )
    product.components.add(component)

    url = reverse("api-1:patch_product", kwargs={"product_id": product.id})
    response = client.patch(url, json.dumps({"is_public": True}), content_type="application/json")

    assert response.status_code == 200
    product.refresh_from_db()
    component.refresh_from_db()
    assert product.is_public is True
    assert component.visibility == Component.Visibility.PRIVATE  # Component remains private


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
    sample_team_with_owner_member,
    sample_user,  # noqa: F811
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
def test_community_plan_put_update_component_allows_public(
    sample_team_with_owner_member,
    sample_user,  # noqa: F811
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
def test_valid_operations_are_allowed(sample_team_with_owner_member, sample_user):  # noqa: F811
    """Test that valid operations are still allowed."""
    client = Client()
    team = sample_team_with_owner_member.team

    BillingPlan.objects.create(
        key="test_plan",
        name="Test Plan",
        max_components=10,
        max_products=10,
    )
    team.billing_plan = "test_plan"
    team.save()

    client.login(username=sample_user.username, password="test")
    setup_test_session(client, team, team.members.first())

    product = Product.objects.create(name="Test Product", team=team, is_public=False)
    component = Component.objects.create(name="Test Component", team=team, visibility=Component.Visibility.PUBLIC)
    product.components.add(component)

    url = reverse("api-1:patch_product", kwargs={"product_id": product.id})
    response = client.patch(url, json.dumps({"is_public": True}), content_type="application/json")

    assert response.status_code == 200
    assert response.json()["is_public"] is True

    response = client.patch(url, json.dumps({"is_public": False}), content_type="application/json")
    assert response.status_code == 200

    component_url = reverse("api-1:patch_component", kwargs={"component_id": component.id})
    response = client.patch(component_url, json.dumps({"visibility": "private"}), content_type="application/json")

    assert response.status_code == 200
    assert response.json()["visibility"] == "private"


@pytest.mark.django_db
def test_workspace_public_view_filters_private_items(sample_team_with_owner_member):
    """Test that workspace public view only shows products with publicly-visible components."""
    team = sample_team_with_owner_member.team
    team.is_public = True
    team.save()

    # Create products with different visibility scenarios
    # 1. Public product with public component - SHOULD SHOW
    product1 = Product.objects.create(name="Product with Public Component", team=team, is_public=True)
    public_component = Component.objects.create(
        name="Public Component", team=team, visibility=Component.Visibility.PUBLIC
    )
    product1.components.add(public_component)

    # 2. Public product with only private components - SHOULD NOT SHOW
    product2 = Product.objects.create(name="Product with Only Private Components", team=team, is_public=True)
    private_component = Component.objects.create(
        name="Private Component", team=team, visibility=Component.Visibility.PRIVATE
    )
    product2.components.add(private_component)

    # 3. Private product - SHOULD NOT SHOW
    Product.objects.create(name="Private Product", team=team, is_public=False)

    # Import view helpers
    from sbomify.apps.core.views.workspace_public import _list_public_products

    # Get public products
    public_products = _list_public_products(team)

    product_names = [p["name"] for p in public_products]
    assert "Product with Public Component" in product_names
    assert "Product with Only Private Components" not in product_names
    assert "Private Product" not in product_names
