import pytest
from django.test import Client
from django.urls import reverse

from billing.models import BillingPlan


@pytest.mark.django_db
class TestUIWorkflows:
    def test_dashboard_stats_load(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that dashboard stats load correctly with Vue component"""
        client.login(username=sample_user.username, password="test")  # nosec B106
        team = sample_team_with_owner_member.team

        # Setup billing plan
        BillingPlan.objects.create(
            key="stats_plan",
            name="Stats Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "stats_plan"
        team.save()

        # Test initial page load
        response = client.get(reverse("core:dashboard"))
        content = response.content.decode()

        # Check Vue component mounting point exists
        assert 'class="vc-dashboard-stats"' in content

        # Test API endpoint for stats (new endpoint, no team_key needed in URL)
        response = client.get(reverse("api-1:get_dashboard_summary"))
        assert response.status_code == 200
        data = response.json()

        # Verify expected stats structure from new endpoint
        assert "total_components" in data
        assert "total_projects" in data
        assert "total_products" in data
        assert "latest_uploads" in data
        assert isinstance(data["latest_uploads"], list)

    def test_progressive_enhancement(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test that forms work without JavaScript and have API fallback"""
        client.login(username=sample_user.username, password="test")  # nosec B106
        team = sample_team_with_owner_member.team

        # Setup billing plan
        BillingPlan.objects.create(
            key="ui_workflow_plan",
            name="UI Workflow Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "ui_workflow_plan"
        team.save()

        # Set current team in session
        session = client.session
        session["current_team"] = {
            "id": team.id,
            "key": team.key,
            "role": "owner"
        }
        session.save()

        # Test form submission without JS
        response = client.post(
            reverse("sboms:components_dashboard"),
            {
                "name": "Test Component",
            }
        )

        # Should redirect on success
        assert response.status_code == 302
        assert response.url == reverse("sboms:components_dashboard")

        # Verify component was created
        from sboms.models import Component
        component = Component.objects.filter(name="Test Component", team_id=team.id).first()
        assert component is not None

        # Test metadata API endpoint with AJAX
        response = client.get(
            reverse("api-1:get_component_metadata", kwargs={"component_id": component.id}),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json"
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
            key="ui_workflow_plan",
            name="UI Workflow Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "ui_workflow_plan"
        team.save()

        # Set current team in session
        session = client.session
        session["current_team"] = {
            "id": team.id,
            "key": team.key,
            "role": "owner"
        }
        session.save()

        # First, verify we can access the components dashboard
        response = client.get(reverse("sboms:components_dashboard"))
        assert response.status_code == 200
        content = response.content.decode()

        # Verify the Add Component button exists
        assert 'data-bs-target="#addComponentModal"' in content
        assert "Add Component" in content

        # Verify the modal form exists with autofocus
        assert 'id="addComponentModal"' in content
        assert "autofocus" in content

        # Submit the form with a random component name
        component_name = "Test Component 123"
        response = client.post(
            reverse("sboms:components_dashboard"),
            {
                "name": component_name,
            },
            follow=True  # Follow the redirect
        )

        # Verify we were redirected back to the dashboard
        assert response.status_code == 200
        assert response.redirect_chain[-1][0] == reverse("sboms:components_dashboard")

        # Verify the component was created
        from sboms.models import Component
        component = Component.objects.filter(name=component_name, team_id=team.id).first()
        assert component is not None

        # Verify the component appears in the dashboard
        content = response.content.decode()
        assert component_name in content