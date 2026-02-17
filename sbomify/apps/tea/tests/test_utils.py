"""
Unit tests for TEA utility functions.
"""

import pytest
from django.test import RequestFactory

from sbomify.apps.tea.utils import (
    DOCUMENT_TYPE_TO_TEA_ARTIFACT,
    get_artifact_mime_type,
    get_tea_artifact_type,
    get_workspace_from_request,
)


class TestGetArtifactMimeType:
    """Tests for get_artifact_mime_type."""

    def test_cyclonedx_mime_type(self):
        assert get_artifact_mime_type("cyclonedx") == "application/vnd.cyclonedx+json"

    def test_spdx_mime_type(self):
        assert get_artifact_mime_type("spdx") == "application/spdx+json"

    def test_unknown_format_returns_default(self):
        assert get_artifact_mime_type("unknown") == "application/json"

    def test_case_insensitive(self):
        assert get_artifact_mime_type("CycloneDX") == "application/vnd.cyclonedx+json"
        assert get_artifact_mime_type("SPDX") == "application/spdx+json"


class TestGetTeaArtifactType:
    """Tests for get_tea_artifact_type."""

    def test_none_returns_other(self):
        assert get_tea_artifact_type(None) == "OTHER"

    def test_empty_string_returns_other(self):
        assert get_tea_artifact_type("") == "OTHER"

    def test_unknown_type_returns_other(self):
        assert get_tea_artifact_type("unknown-type") == "OTHER"

    def test_all_known_mappings(self):
        for doc_type, tea_type in DOCUMENT_TYPE_TO_TEA_ARTIFACT.items():
            assert get_tea_artifact_type(doc_type) == tea_type

    def test_threat_model(self):
        assert get_tea_artifact_type("threat-model") == "THREAT_MODEL"

    def test_license(self):
        assert get_tea_artifact_type("license") == "LICENSE"

    def test_release_notes(self):
        assert get_tea_artifact_type("release-notes") == "RELEASE_NOTES"

    def test_changelog_maps_to_release_notes(self):
        assert get_tea_artifact_type("changelog") == "RELEASE_NOTES"


@pytest.mark.django_db
class TestGetWorkspaceFromRequest:
    """Tests for get_workspace_from_request."""

    def test_workspace_key_resolves(self, tea_enabled_product):
        """Test workspace resolution via workspace_key."""
        tea_enabled_product.team.is_public = True
        tea_enabled_product.team.save()

        factory = RequestFactory()
        request = factory.get("/")

        result = get_workspace_from_request(request, workspace_key=tea_enabled_product.team.key)
        assert result == tea_enabled_product.team

    def test_nonexistent_workspace_key_returns_error(self):
        """Test that non-existent workspace key returns error string."""
        factory = RequestFactory()
        request = factory.get("/")

        result = get_workspace_from_request(request, workspace_key="nonexistent-key")
        assert isinstance(result, str)
        assert "not found" in result.lower() or "not accessible" in result.lower()

    def test_no_workspace_key_returns_error(self):
        """Test that missing workspace key returns error string."""
        factory = RequestFactory()
        request = factory.get("/")

        result = get_workspace_from_request(request)
        assert isinstance(result, str)

    def test_tea_disabled_returns_error(self, sample_product):
        """Test that TEA disabled returns specific error."""
        sample_product.team.tea_enabled = False
        sample_product.team.is_public = True
        sample_product.team.save()

        factory = RequestFactory()
        request = factory.get("/")

        result = get_workspace_from_request(request, workspace_key=sample_product.team.key)
        assert isinstance(result, str)
        assert "not enabled" in result.lower()

    def test_custom_domain_resolves(self, tea_enabled_product):
        """Test workspace resolution via custom domain."""
        team = tea_enabled_product.team
        team.custom_domain = "trust.example.com"
        team.custom_domain_validated = True
        team.is_public = True
        team.save()

        factory = RequestFactory()
        request = factory.get("/")
        request.is_custom_domain = True
        request.custom_domain_team = team

        result = get_workspace_from_request(request)
        assert result == team

    def test_custom_domain_unvalidated_returns_error(self, tea_enabled_product):
        """C2: Unvalidated custom domain is rejected."""
        team = tea_enabled_product.team
        team.custom_domain = "trust.example.com"
        team.custom_domain_validated = False
        team.is_public = True
        team.save()

        factory = RequestFactory()
        request = factory.get("/")
        request.is_custom_domain = True
        request.custom_domain_team = team

        result = get_workspace_from_request(request)
        assert isinstance(result, str)
        assert "not validated" in result.lower()

    def test_custom_domain_not_public_returns_error(self, tea_enabled_product):
        """C1: Non-public workspace via custom domain is rejected."""
        team = tea_enabled_product.team
        team.custom_domain = "trust.example.com"
        team.custom_domain_validated = True
        team.is_public = False
        team.save()

        factory = RequestFactory()
        request = factory.get("/")
        request.is_custom_domain = True
        request.custom_domain_team = team

        result = get_workspace_from_request(request)
        assert isinstance(result, str)
        assert "not accessible" in result.lower()

    def test_check_tea_enabled_false_skips_check(self, sample_product):
        """Test that check_tea_enabled=False skips TEA check."""
        sample_product.team.tea_enabled = False
        sample_product.team.is_public = True
        sample_product.team.save()

        factory = RequestFactory()
        request = factory.get("/")

        result = get_workspace_from_request(
            request, workspace_key=sample_product.team.key, check_tea_enabled=False
        )
        assert result == sample_product.team


@pytest.mark.django_db
class TestCrossWorkspaceIsolation:
    """H5: Cross-workspace isolation tests."""

    def test_product_not_visible_in_other_workspace(self, tea_enabled_product):
        """Test that products from one workspace aren't visible in another."""
        from django.test import Client

        from sbomify.apps.teams.models import Team

        other_team = Team.objects.create(name="Other Team", key="other-ws", tea_enabled=True, is_public=True)

        client = Client()
        url = f"/tea/v1/product/{tea_enabled_product.id}?workspace_key={other_team.key}"
        response = client.get(url)

        assert response.status_code == 404
        other_team.delete()

    def test_component_not_visible_in_other_workspace(self, tea_enabled_component):
        """Test that components from one workspace aren't visible in another."""
        from django.test import Client

        from sbomify.apps.teams.models import Team

        other_team = Team.objects.create(name="Other Team", key="other-ws-2", tea_enabled=True, is_public=True)

        client = Client()
        url = f"/tea/v1/component/{tea_enabled_component.id}?workspace_key={other_team.key}"
        response = client.get(url)

        assert response.status_code == 404
        other_team.delete()
