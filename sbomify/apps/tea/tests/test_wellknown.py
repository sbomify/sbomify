"""
Tests for TEA .well-known/tea endpoint.
"""

import json

import pytest
from django.test import Client, RequestFactory

from sbomify.apps.tea.mappers import TEA_API_VERSION
from sbomify.apps.tea.wellknown import tea_wellknown


@pytest.mark.django_db
class TestTEAWellKnownEndpoint:
    """Tests for /.well-known/tea endpoint."""

    def test_wellknown_on_custom_domain(self, sample_team):
        """Test .well-known/tea on a custom domain."""
        sample_team.custom_domain = "trust.example.com"
        sample_team.custom_domain_validated = True
        sample_team.tea_enabled = True
        sample_team.save()

        # Create a mock request with custom domain attributes
        factory = RequestFactory()
        request = factory.get("/.well-known/tea")
        request.is_custom_domain = True
        request.custom_domain_team = sample_team

        response = tea_wellknown(request)

        assert response.status_code == 200

        data = json.loads(response.content)
        assert data["schemaVersion"] == 1
        assert "endpoints" in data
        assert len(data["endpoints"]) == 1

        endpoint = data["endpoints"][0]
        assert endpoint["url"] == "https://trust.example.com/tea/v1"
        assert TEA_API_VERSION in endpoint["versions"]
        assert endpoint["priority"] == 1

    def test_wellknown_not_on_custom_domain(self, sample_team):
        """Test .well-known/tea when not on a custom domain."""
        factory = RequestFactory()
        request = factory.get("/.well-known/tea")
        request.is_custom_domain = False
        request.custom_domain_team = None

        response = tea_wellknown(request)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "error" in data

    def test_wellknown_unvalidated_custom_domain(self, sample_team):
        """Test .well-known/tea with unvalidated custom domain."""
        sample_team.custom_domain = "trust.example.com"
        sample_team.custom_domain_validated = False
        sample_team.save()

        factory = RequestFactory()
        request = factory.get("/.well-known/tea")
        request.is_custom_domain = True
        request.custom_domain_team = sample_team

        response = tea_wellknown(request)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert "not validated" in data["error"]

    def test_wellknown_response_structure(self, sample_team):
        """Test that .well-known/tea response matches the schema."""
        sample_team.custom_domain = "trust.example.com"
        sample_team.custom_domain_validated = True
        sample_team.tea_enabled = True
        sample_team.save()

        factory = RequestFactory()
        request = factory.get("/.well-known/tea")
        request.is_custom_domain = True
        request.custom_domain_team = sample_team

        response = tea_wellknown(request)
        data = json.loads(response.content)

        # Validate schema structure
        assert isinstance(data["schemaVersion"], int)
        assert data["schemaVersion"] == 1

        assert isinstance(data["endpoints"], list)
        assert len(data["endpoints"]) >= 1

        for endpoint in data["endpoints"]:
            assert "url" in endpoint
            assert "versions" in endpoint
            assert isinstance(endpoint["versions"], list)
            assert len(endpoint["versions"]) >= 1
            # Priority should be between 0 and 1
            if "priority" in endpoint:
                assert 0 <= endpoint["priority"] <= 1

    def test_wellknown_tea_disabled(self, sample_team):
        """Test .well-known/tea when TEA is disabled."""
        sample_team.custom_domain = "trust.example.com"
        sample_team.custom_domain_validated = True
        sample_team.tea_enabled = False
        sample_team.save()

        factory = RequestFactory()
        request = factory.get("/.well-known/tea")
        request.is_custom_domain = True
        request.custom_domain_team = sample_team

        response = tea_wellknown(request)

        assert response.status_code == 404
        data = json.loads(response.content)
        assert "not enabled" in data["error"]


@pytest.mark.django_db
class TestTEAWellKnownIntegration:
    """Integration tests for .well-known/tea via Django test client."""

    def test_wellknown_url_accessible(self, sample_team):
        """Test that /.well-known/tea URL is accessible."""
        # Note: Without custom domain middleware setup, this will return 400
        client = Client()
        response = client.get("/.well-known/tea")

        # Should get a response (either 200 or 400 depending on domain)
        assert response.status_code in [200, 400]

    def test_wellknown_returns_json(self, sample_team):
        """Test that .well-known/tea returns JSON content type."""
        sample_team.custom_domain = "trust.example.com"
        sample_team.custom_domain_validated = True
        sample_team.tea_enabled = True
        sample_team.save()

        factory = RequestFactory()
        request = factory.get("/.well-known/tea")
        request.is_custom_domain = True
        request.custom_domain_team = sample_team

        response = tea_wellknown(request)

        assert response["Content-Type"] == "application/json"
