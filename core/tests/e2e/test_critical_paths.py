import json

import pytest
from django.test import Client
from django.urls import reverse

from billing.models import BillingPlan


@pytest.mark.django_db
class TestCriticalPaths:
    def test_component_creation_to_view(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test full workflow: Create component -> View details -> Update metadata"""
        client.login(username=sample_user.username, password="test")  # nosec B106
        team = sample_team_with_owner_member.team

        # Setup billing plan
        BillingPlan.objects.create(
            key="e2e_plan",
            name="E2E Test Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "e2e_plan"
        team.save()

        # Set current team in session
        session = client.session
        session["current_team"] = {
            "id": team.id,
            "key": team.key,
            "role": "owner"
        }
        session.save()

        # 1. Create component via form submission
        response = client.post(
            reverse("sboms:components_dashboard"),
            {
                "name": "E2E Test Component"
            }
        )
        assert response.status_code == 302
        assert response.url == reverse("sboms:components_dashboard")

        # Get the created component
        from sboms.models import Component
        component = Component.objects.filter(name="E2E Test Component", team_id=team.id).first()
        assert component is not None

        # 2. View component details
        response = client.get(
            reverse("sboms:component_details", kwargs={"component_id": component.id})
        )
        content = response.content.decode()
        assert response.status_code == 200
        assert "E2E Test Component" in content

        # 3. Update component metadata via API
        metadata = {
            "supplier": {
                "name": "Updated Supplier",
                "url": ["http://example.com"]
            }
        }
        response = client.put(
            reverse("api-1:get_component_metadata", kwargs={"component_id": component.id}),
            data=json.dumps(metadata),
            content_type="application/json"
        )
        assert response.status_code == 204

        # 4. Verify metadata update via API
        response = client.get(
            reverse("api-1:get_component_metadata", kwargs={"component_id": component.id}),
            content_type="application/json"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["supplier"]["name"] == "Updated Supplier"
        assert data["supplier"]["url"] == ["http://example.com"]

    def test_public_private_toggle(self, client: Client, sample_user, sample_component, sample_team_with_owner_member):
        """Test toggling component public/private status"""
        client.login(username=sample_user.username, password="test")  # nosec B106

        # Ensure component belongs to the team
        team = sample_team_with_owner_member.team

        # Setup billing plan
        BillingPlan.objects.create(
            key="e2e_plan",
            name="E2E Test Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "e2e_plan"
        team.save()

        sample_component.team = team
        sample_component.save()

        # Set current team in session
        session = client.session
        session["current_team"] = {
            "id": team.id,
            "key": team.key,
            "role": "owner"
        }
        session.save()

        # 1. View initial state
        response = client.get(
            reverse("sboms:component_details", kwargs={"component_id": sample_component.id})
        )
        assert response.status_code == 200

        # 2. Toggle public status via API
        response = client.patch(
            reverse("api-1:patch_item_public_status", kwargs={
                "item_type": "component",
                "item_id": sample_component.id
            }),
            data=json.dumps({"is_public": True}),
            content_type="application/json"
        )
        assert response.status_code == 200
        assert response.json()["is_public"] is True

        # 3. Verify public access
        client.logout()
        response = client.get(
            reverse("sboms:component_details_public", kwargs={"component_id": sample_component.id})
        )
        assert response.status_code == 200

    def test_create_and_copy_token(self, client: Client, sample_user, sample_team_with_owner_member):
        """Test creating and copying an access token."""
        client.login(username=sample_user.username, password="test")  # nosec B106
        team = sample_team_with_owner_member.team

        # Setup billing plan
        BillingPlan.objects.create(
            key="e2e_plan",
            name="E2E Test Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "e2e_plan"
        team.save()

        # Set current team in session
        session = client.session
        session["current_team"] = {
            "id": team.id,
            "key": team.key,
            "role": "owner"
        }
        session.save()

        # Create a new token
        response = client.post(
            reverse("core:settings"),
            {"description": "Test Token"},
            follow=True
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert "Test Token" in content
        assert 'id="access-token"' in content  # Verify the token field exists
        assert 'class="vc-copy-token"' in content  # Verify the copy button exists

        # Verify token appears in list
        response = client.get(reverse("core:settings"))
        assert response.status_code == 200
        content = response.content.decode()
        assert "Test Token" in content

        # Delete the token
        from access_tokens.models import AccessToken
        token = AccessToken.objects.get(description="Test Token")
        response = client.post(
            reverse("core:delete_access_token", kwargs={"token_id": token.id}),
            follow=True
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert "Test Token" not in content

    def test_page_titles(self, client: Client, sample_user, sample_team_with_owner_member, sample_component):
        """Test that all pages have proper titles."""
        client.login(username=sample_user.username, password="test")  # nosec B106
        team = sample_team_with_owner_member.team

        # Setup billing plan
        BillingPlan.objects.create(
            key="e2e_plan",
            name="E2E Test Plan",
            max_components=10,
            max_products=10,
            max_projects=10
        )
        team.billing_plan = "e2e_plan"
        team.save()

        component = sample_component
        component.team = team
        component.save()

        # Set current team in session
        session = client.session
        session["current_team"] = {
            "id": team.id,
            "key": team.key,
            "role": "owner"
        }
        session.save()

        # Test core pages
        response = client.get(reverse("core:settings"))
        assert "sbomify Settings" in response.content.decode()

        # Test sboms pages
        response = client.get(reverse("sboms:components_dashboard"))
        assert "sbomify Components" in response.content.decode()

        response = client.get(reverse("sboms:component_details", kwargs={"component_id": component.id}))
        assert f"sbomify Component: {component.name}" in response.content.decode()

        # Test teams pages
        response = client.get(reverse("teams:team_details", kwargs={"team_key": team.key}))
        assert f"sbomify Team: {team.name}" in response.content.decode()

        response = client.get(reverse("teams:team_settings", kwargs={"team_key": team.key}))
        assert f"sbomify Team Settings: {team.name}" in response.content.decode()