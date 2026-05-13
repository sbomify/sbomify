"""
Tests for sboms_table service module.

Tests for build_sboms_table_context() and delete_sbom_from_request().
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory

from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.sboms.services.sboms_table import (
    build_sboms_table_context,
    delete_sbom_from_request,
)

from .fixtures import (  # noqa: F401
    sample_billing_plan,
    sample_component,
    sample_product,
    sample_sbom,
    sample_team_with_owner_member,
    sample_user,
)


@pytest.fixture
def mock_request():
    """Create a mock request object."""
    factory = RequestFactory()
    request = factory.get("/")
    request.session = {}
    return request


@pytest.mark.django_db
class TestBuildSbomsTableContext:
    """Tests for build_sboms_table_context()"""

    @patch("sbomify.apps.plugins.apis.get_sbom_assessment_badge")
    @patch("sbomify.apps.sboms.services.sboms_table.list_component_sboms")
    @patch("sbomify.apps.sboms.services.sboms_table.get_component")
    def test_success(
        self,
        mock_get_component,
        mock_list_sboms,
        mock_assessment_badge,
        mock_request,
    ):
        """Returns ServiceResult.success with context dict."""
        mock_get_component.return_value = (
            200,
            {"id": "comp123", "has_crud_permissions": True, "team_id": 1},
        )
        mock_list_sboms.return_value = (200, {"items": []})
        mock_assessment_badge.return_value = MagicMock(model_dump=lambda: {"status": "pass"})

        result = build_sboms_table_context(mock_request, "comp123", is_public_view=True)

        assert result.ok is True
        assert "component_id" in result.value
        assert "sboms" in result.value
        assert "is_public_view" in result.value

    @patch("sbomify.apps.sboms.services.sboms_table.get_component")
    def test_component_not_found(self, mock_get_component, mock_request):
        """Returns failure when component not found."""
        mock_get_component.return_value = (404, {"detail": "Component not found"})

        result = build_sboms_table_context(mock_request, "nonexistent", is_public_view=True)

        assert result.ok is False
        assert "not found" in result.error.lower()

    @patch("sbomify.apps.sboms.services.sboms_table.list_component_sboms")
    @patch("sbomify.apps.sboms.services.sboms_table.get_component")
    def test_sboms_not_found(self, mock_get_component, mock_list_sboms, mock_request):
        """Returns failure when list_component_sboms fails."""
        mock_get_component.return_value = (
            200,
            {"id": "comp123", "has_crud_permissions": True},
        )
        mock_list_sboms.return_value = (500, {"detail": "Database error"})

        result = build_sboms_table_context(mock_request, "comp123", is_public_view=True)

        assert result.ok is False

    @patch("sbomify.apps.plugins.apis.get_sbom_assessment_badge")
    @patch("sbomify.apps.sboms.services.sboms_table.list_component_sboms")
    @patch("sbomify.apps.sboms.services.sboms_table.get_component")
    def test_sorts_by_name_then_date(
        self,
        mock_get_component,
        mock_list_sboms,
        mock_assessment_badge,
        mock_request,
    ):
        """SBOMs sorted alphabetically by name, then newest first."""
        from datetime import datetime, timezone

        mock_get_component.return_value = (
            200,
            {"id": "comp123", "has_crud_permissions": True},
        )

        # Create sboms with different names and dates
        sboms = [
            {"sbom": {"id": 1, "name": "zebra", "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc)}},
            {"sbom": {"id": 2, "name": "alpha", "created_at": datetime(2025, 1, 2, tzinfo=timezone.utc)}},
            {"sbom": {"id": 3, "name": "alpha", "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc)}},
        ]
        mock_list_sboms.return_value = (200, {"items": sboms})
        mock_assessment_badge.return_value = MagicMock(model_dump=lambda: {})

        result = build_sboms_table_context(mock_request, "comp123", is_public_view=True)

        assert result.ok is True
        # First should be "alpha" (alphabetical), and between alphas, newer first
        sorted_sboms = result.value["sboms"]
        assert sorted_sboms[0]["sbom"]["name"] == "alpha"
        assert sorted_sboms[0]["sbom"]["id"] == 2  # Newer alpha first
        assert sorted_sboms[1]["sbom"]["name"] == "alpha"
        assert sorted_sboms[1]["sbom"]["id"] == 3  # Older alpha second
        assert sorted_sboms[2]["sbom"]["name"] == "zebra"

    @patch("sbomify.apps.sboms.services.sboms_table.list_component_sboms")
    @patch("sbomify.apps.sboms.services.sboms_table.get_component")
    def test_passes_through_assessments_from_inner_api(
        self,
        mock_get_component,
        mock_list_sboms,
        mock_request,
    ):
        """``assessments`` is populated by ``list_component_sboms`` directly.

        The badge enrichment loop was removed in the N+1 refactor — the
        inner API now returns everything the table renders, so this test
        verifies the context layer preserves the inner payload verbatim
        rather than re-fetching it.
        """
        from datetime import datetime, timezone

        mock_get_component.return_value = (
            200,
            {"id": "comp123", "has_crud_permissions": True},
        )
        assessments_payload = {
            "sbom_id": "1",
            "overall_status": "all_pass",
            "total_assessments": 1,
            "passing_count": 1,
            "failing_count": 0,
            "pending_count": 0,
            "skipped_count": 0,
            "plugins": [
                {"name": "ntia-minimum-elements-2021", "display_name": "NTIA", "status": "pass", "findings_count": 7}
            ],
        }
        mock_list_sboms.return_value = (
            200,
            {
                "items": [
                    {
                        "sbom": {
                            "id": 1,
                            "name": "test",
                            "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                        },
                        "assessments": assessments_payload,
                    }
                ]
            },
        )

        result = build_sboms_table_context(mock_request, "comp123", is_public_view=True)

        assert result.ok is True
        assert result.value["sboms"][0]["assessments"] == assessments_payload

    @patch("sbomify.apps.sboms.services.sboms_table.list_component_sboms")
    @patch("sbomify.apps.sboms.services.sboms_table.get_component")
    def test_missing_inner_assessments_is_passed_through(
        self,
        mock_get_component,
        mock_list_sboms,
        mock_request,
    ):
        """If the inner API didn't include ``assessments`` (e.g. legacy
        cached payload), the context layer must not invent one — it
        passes the item through unchanged rather than re-fetching."""
        from datetime import datetime, timezone

        mock_get_component.return_value = (
            200,
            {"id": "comp123", "has_crud_permissions": True},
        )
        mock_list_sboms.return_value = (
            200,
            {
                "items": [
                    {
                        "sbom": {
                            "id": 1,
                            "name": "test",
                            "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                        }
                    }
                ]
            },
        )

        result = build_sboms_table_context(mock_request, "comp123", is_public_view=True)

        assert result.ok is True
        # No surreptitious extra DB / HTTP fetch — whatever the API gave us is what the template gets.
        assert result.value["sboms"][0].get("assessments") is None

    @patch("sbomify.apps.sboms.services.sboms_table.list_component_sboms")
    @patch("sbomify.apps.sboms.services.sboms_table.get_component")
    def test_public_view_no_team_fetch(self, mock_get_component, mock_list_sboms, mock_request):
        """is_public_view=True skips team fetch."""
        mock_get_component.return_value = (
            200,
            {"id": "comp123", "has_crud_permissions": True},
        )
        mock_list_sboms.return_value = (200, {"items": []})

        with patch("sbomify.apps.sboms.services.sboms_table.get_team") as mock_get_team:
            result = build_sboms_table_context(mock_request, "comp123", is_public_view=True)

            assert result.ok is True
            # get_team should NOT be called for public view
            mock_get_team.assert_not_called()
            assert "team_billing_plan" not in result.value

    @patch("sbomify.apps.sboms.services.sboms_table.get_team")
    @patch("sbomify.apps.sboms.services.sboms_table.list_component_sboms")
    @patch("sbomify.apps.sboms.services.sboms_table.get_component")
    def test_private_view_includes_team_data(self, mock_get_component, mock_list_sboms, mock_get_team, mock_request):
        """Private view includes team_billing_plan and team_key."""
        mock_get_component.return_value = (
            200,
            {"id": "comp123", "has_crud_permissions": True, "team_id": 123},
        )
        mock_list_sboms.return_value = (200, {"items": []})

        # Mock team response
        mock_team = MagicMock()
        mock_team.billing_plan = "business"
        mock_get_team.return_value = (200, mock_team)

        result = build_sboms_table_context(mock_request, "comp123", is_public_view=False)

        assert result.ok is True
        assert "team_billing_plan" in result.value
        assert "team_key" in result.value
        assert "delete_form" in result.value

    @patch("sbomify.apps.sboms.services.sboms_table.list_component_sboms")
    @patch("sbomify.apps.sboms.services.sboms_table.get_component")
    def test_has_crud_permissions(self, mock_get_component, mock_list_sboms, mock_request):
        """Passes through has_crud_permissions from component."""
        mock_get_component.return_value = (
            200,
            {"id": "comp123", "has_crud_permissions": True},
        )
        mock_list_sboms.return_value = (200, {"items": []})

        result = build_sboms_table_context(mock_request, "comp123", is_public_view=True)

        assert result.ok is True
        assert result.value["has_crud_permissions"] is True


@pytest.mark.django_db
class TestDeleteSbomFromRequest:
    """Tests for delete_sbom_from_request()"""

    def test_invalid_form(self, mock_request):
        """Invalid form returns failure with errors."""
        # POST without required sbom_id
        factory = RequestFactory()
        request = factory.post("/", {})

        result = delete_sbom_from_request(request)

        assert result.ok is False
        assert result.error is not None

    @patch("sbomify.apps.sboms.services.sboms_table.delete_sbom_record")
    def test_success(self, mock_delete_record):
        """Returns ServiceResult.success() on valid delete."""
        mock_delete_record.return_value = ServiceResult.success()

        factory = RequestFactory()
        request = factory.post("/", {"sbom_id": "sbom123"})

        result = delete_sbom_from_request(request)

        assert result.ok is True
        mock_delete_record.assert_called_once()

    @patch("sbomify.apps.sboms.services.sboms_table.delete_sbom_record")
    def test_propagates_error(self, mock_delete_record):
        """Propagates failure from delete_sbom_record."""
        mock_delete_record.return_value = ServiceResult.failure("SBOM not found", status_code=404)

        factory = RequestFactory()
        request = factory.post("/", {"sbom_id": "sbom123"})

        result = delete_sbom_from_request(request)

        assert result.ok is False
        assert "not found" in result.error.lower()
        assert result.status_code == 404
