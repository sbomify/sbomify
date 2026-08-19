import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.billing.models import BillingPlan


@pytest.mark.django_db
class TestUIWorkflows:
    def test_dashboard_stats_load(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that dashboard stats load correctly"""
        client.login(username=sample_user.username, password="test")  # nosec B106
        team = sample_team_with_owner_member.team

        # Mark wizard as completed to avoid redirect to onboarding
        session = client.session
        session["current_team"] = {
            "key": team.key,
            "role": "owner",
            "has_completed_wizard": True,
        }
        session.save()

        # Mark plan as selected so the plan selection redirect is skipped
        team.has_selected_billing_plan = True
        team.save(update_fields=["has_selected_billing_plan"])

        # Setup billing plan
        BillingPlan.objects.create(
            key="stats_plan", name="Stats Plan", max_components=10, max_products=10
        )
        team.billing_plan = "stats_plan"
        team.save()

        # Test initial page load
        response = client.get(reverse("core:dashboard"))
        content = response.content.decode()

        # Check dashboard page loads with expected content
        assert "Dashboard" in content
        assert "space-y-6" in content  # Main dashboard layout class

        # Test API endpoint for stats (new endpoint, no team_key needed in URL)
        response = client.get(reverse("api-1:get_dashboard_summary"))
        assert response.status_code == 200
        data = response.json()

        assert "total_components" in data
        assert "total_products" in data
        assert "latest_uploads" in data
        assert isinstance(data["latest_uploads"], list)

    def test_api_first_architecture(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that the new API-first architecture works correctly"""
        import json

        client.login(username=sample_user.username, password="test")  # nosec B106
        team = sample_team_with_owner_member.team

        # Setup billing plan
        BillingPlan.objects.create(
            key="ui_workflow_plan", name="UI Workflow Plan", max_components=10, max_products=10
        )
        team.billing_plan = "ui_workflow_plan"
        team.save()

        # Set current team in session
        session = client.session
        session["current_team"] = {"id": team.id, "key": team.key, "role": "owner"}
        session.save()

        # Test API-based component creation
        response = client.post(
            reverse("api-1:create_component"),
            data=json.dumps(
                {
                    "name": "Test Component",
                }
            ),
            content_type="application/json",
        )

        # Should return JSON success response
        assert response.status_code == 201
        component_data = response.json()
        assert component_data["name"] == "Test Component"

        # Verify component was created
        from sbomify.apps.sboms.models import Component

        component = Component.objects.get(id=component_data["id"])
        assert component.name == "Test Component"

        # Test metadata API endpoint with AJAX
        response = client.get(
            reverse("api-1:get_component_metadata", kwargs={"component_id": component.id}),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )

        # Should return JSON response for AJAX request
        assert response.status_code == 200
        assert response.headers.get("content-type").startswith("application/json")

    def test_component_creation_workflow(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test the component creation workflow from the dashboard."""
        client.login(username=sample_user.username, password="test")  # nosec B106
        team = sample_team_with_owner_member.team

        # Setup billing plan
        BillingPlan.objects.create(
            key="ui_workflow_plan", name="UI Workflow Plan", max_components=10, max_products=10
        )
        team.billing_plan = "ui_workflow_plan"
        team.save()

        # Set current team in session
        session = client.session
        session["current_team"] = {"id": team.id, "key": team.key, "role": "owner"}
        session.save()

        # First, verify we can access the components dashboard
        response = client.get(reverse("core:components_dashboard"))
        assert response.status_code == 200
        content = response.content.decode()

        # Verify the components page links to the create page. The form itself
        # moved off the dashboard and onto its own page.
        assert "Components" in content
        assert reverse("core:component_new") in content

        response = client.get(reverse("core:component_new"))
        assert response.status_code == 200
        assert 'name="component_type"' in response.content.decode()

        # Test API-based component creation
        import json

        component_name = "Test Component 123"
        response = client.post(
            reverse("api-1:create_component"),
            data=json.dumps(
                {
                    "name": component_name,
                }
            ),
            content_type="application/json",
        )

        # Verify API response
        assert response.status_code == 201
        component_data = response.json()
        assert component_data["name"] == component_name

        # Verify the component was created
        from sbomify.apps.sboms.models import Component

        component = Component.objects.get(id=component_data["id"])
        assert component.name == component_name

        # Verify the component appears in the API list
        response = client.get(reverse("api-1:list_components"))
        assert response.status_code == 200
        components_data = response.json()
        component_names = [c["name"] for c in components_data["items"]]
        assert component_name in component_names

    def test_product_create_page_post_redirects_to_the_product(
        self, client: Client, sample_user, sample_team_with_owner_member
    ):
        """Posting the New Product form lands on the created product's page.

        Pins the success path of `_create_product`: the API helper hands back
        a response *dict*, so the redirect must read the id by key.
        """
        client.login(username=sample_user.username, password="test")  # nosec B106
        team = sample_team_with_owner_member.team

        BillingPlan.objects.create(
            key="product_create_plan", name="Product Create Plan", max_components=10, max_products=10
        )
        team.billing_plan = "product_create_plan"
        team.save()

        session = client.session
        session["current_team"] = {"id": team.id, "key": team.key, "role": "owner"}
        session.save()

        response = client.post(
            reverse("core:product_new"),
            data={"name": "Page Created Product", "description": "From the create page"},
        )

        from sbomify.apps.core.models import Product

        product = Product.objects.get(name="Page Created Product", team=team)
        assert response.status_code == 302
        assert response.url == reverse("core:product_details", kwargs={"product_id": product.id})

    def test_products_dashboard_post_shim_redirects_to_the_product(
        self, client: Client, sample_user, sample_team_with_owner_member
    ):
        """The compatibility POST shim on the list URL takes the same success path."""
        client.login(username=sample_user.username, password="test")  # nosec B106
        team = sample_team_with_owner_member.team

        BillingPlan.objects.create(
            key="product_shim_plan", name="Product Shim Plan", max_components=10, max_products=10
        )
        team.billing_plan = "product_shim_plan"
        team.save()

        session = client.session
        session["current_team"] = {"id": team.id, "key": team.key, "role": "owner"}
        session.save()

        response = client.post(
            reverse("core:products_dashboard"),
            data={"name": "Shim Created Product", "description": ""},
        )

        from sbomify.apps.core.models import Product

        product = Product.objects.get(name="Shim Created Product", team=team)
        assert response.status_code == 302
        assert response.url == reverse("core:product_details", kwargs={"product_id": product.id})

    def test_component_create_page_post_redirects_to_the_component(
        self, client: Client, sample_user, sample_team_with_owner_member
    ):
        """Posting the New Component form lands on the created component's page."""
        client.login(username=sample_user.username, password="test")  # nosec B106
        team = sample_team_with_owner_member.team

        BillingPlan.objects.create(
            key="component_create_plan", name="Component Create Plan", max_components=10, max_products=10
        )
        team.billing_plan = "component_create_plan"
        team.save()

        session = client.session
        session["current_team"] = {"id": team.id, "key": team.key, "role": "owner"}
        session.save()

        response = client.post(
            reverse("core:component_new"),
            data={"name": "Page Created Component", "component_type": "bom"},
        )

        from sbomify.apps.sboms.models import Component

        component = Component.objects.get(name="Page Created Component", team=team)
        assert response.status_code == 302
        assert response.url == reverse("core:component_details", kwargs={"component_id": component.id})

    def test_components_dashboard_post_shim_redirects_to_the_component(
        self, client: Client, sample_user, sample_team_with_owner_member
    ):
        """The compatibility POST shim on the list URL takes the same success path."""
        client.login(username=sample_user.username, password="test")  # nosec B106
        team = sample_team_with_owner_member.team

        BillingPlan.objects.create(
            key="component_shim_plan", name="Component Shim Plan", max_components=10, max_products=10
        )
        team.billing_plan = "component_shim_plan"
        team.save()

        session = client.session
        session["current_team"] = {"id": team.id, "key": team.key, "role": "owner"}
        session.save()

        response = client.post(
            reverse("core:components_dashboard"),
            data={"name": "Shim Created Component", "component_type": "bom"},
        )

        from sbomify.apps.sboms.models import Component

        component = Component.objects.get(name="Shim Created Component", team=team)
        assert response.status_code == 302
        assert response.url == reverse("core:component_details", kwargs={"component_id": component.id})
