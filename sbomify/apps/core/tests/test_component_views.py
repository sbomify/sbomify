
import pytest
from django.test import Client
from django.urls import reverse
from sbomify.apps.sboms.models import Component
from sbomify.apps.core.tests.fixtures import sample_user
from sbomify.apps.teams.fixtures import sample_team_with_owner_member
from sbomify.apps.sboms.tests.test_views import setup_test_session

@pytest.mark.django_db
class TestComponentDetailsViews:
    def setup_method(self):
        self.client = Client()

    def test_private_sbom_component_template(self, sample_team_with_owner_member, sample_user):
        """Test that private SBOM component renders the correct template."""
        team = sample_team_with_owner_member.team
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, sample_user)

        component = Component.objects.create(
            name="Private SBOM Component",
            team=team,
            component_type=Component.ComponentType.SBOM,
            is_public=False
        )

        url = reverse("core:component_details", kwargs={"component_id": component.id})
        response = self.client.get(url)
        
        assert response.status_code == 200
        # Verify specific template usage indirectly via content or context if direct template check isn't easy with client
        # Django test client 'response.templates' can be checked
        templates = [t.name for t in response.templates]
        assert "core/component_details_private_sbom.html.j2" in templates

    def test_private_document_component_template(self, sample_team_with_owner_member, sample_user):
        """Test that private Document component renders the correct template."""
        team = sample_team_with_owner_member.team
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, sample_user)

        component = Component.objects.create(
            name="Private Document Component",
            team=team,
            component_type=Component.ComponentType.DOCUMENT,
            is_public=False
        )

        url = reverse("core:component_details", kwargs={"component_id": component.id})
        response = self.client.get(url)
        
        assert response.status_code == 200
        templates = [t.name for t in response.templates]
        assert "core/component_details_private_document.html.j2" in templates

    def test_public_sbom_component_template(self, sample_team_with_owner_member):
        """Test that public SBOM component renders the correct template."""
        team = sample_team_with_owner_member.team
        component = Component.objects.create(
            name="Public SBOM Component",
            team=team,
            component_type=Component.ComponentType.SBOM,
            is_public=True
        )

        url = reverse("core:component_details_public", kwargs={"component_id": component.id})
        response = self.client.get(url)
        
        assert response.status_code == 200
        templates = [t.name for t in response.templates]
        assert "core/component_details_public_sbom.html.j2" in templates

    def test_public_document_component_template(self, sample_team_with_owner_member):
        """Test that public Document component renders the correct template."""
        team = sample_team_with_owner_member.team
        component = Component.objects.create(
            name="Public Document Component",
            team=team,
            component_type=Component.ComponentType.DOCUMENT,
            is_public=True
        )

        url = reverse("core:component_details_public", kwargs={"component_id": component.id})
        response = self.client.get(url)
        
        assert response.status_code == 200
        templates = [t.name for t in response.templates]
        assert "core/component_details_public_document.html.j2" in templates

    def test_component_not_found(self, sample_team_with_owner_member, sample_user):
        """Test 404 for non-existent component."""
        team = sample_team_with_owner_member.team
        self.client.login(username=sample_user.username, password="test")
        setup_test_session(self.client, team, sample_user)

        url = reverse("core:component_details", kwargs={"component_id": "999999"})
        response = self.client.get(url)
        assert response.status_code == 404

    def test_public_access_to_private_component_denied(self, sample_team_with_owner_member):
        """Test that public access to private component returns 403."""
        team = sample_team_with_owner_member.team
        component = Component.objects.create(
            name="Private Component",
            team=team,
            component_type=Component.ComponentType.SBOM,
            is_public=False
        )

        url = reverse("core:component_details_public", kwargs={"component_id": component.id})
        response = self.client.get(url)
        assert response.status_code == 403 
