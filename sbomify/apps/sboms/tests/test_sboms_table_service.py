"""
Tests for sboms_table service module.

Tests for build_sboms_table_context() and delete_sbom_from_request().
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test import RequestFactory

from sbomify.apps.core.services.results import ServiceResult
from sbomify.apps.sboms.services.sboms_table import (
    _summary_artifacts,
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

        # ?full=1 returns the whole history (the component card otherwise shows
        # only the latest artifact of each type), so the sort order is testable.
        full_request = RequestFactory().get("/?full=1")
        full_request.session = {}
        result = build_sboms_table_context(full_request, "comp123", is_public_view=True)

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


def _artifact(name: str, fmt: str, bom_type: str | None, day: int) -> dict:
    from datetime import datetime, timezone

    return {
        "sbom": {
            "id": name,
            "name": name,
            "format": fmt,
            "bom_type": bom_type,
            "created_at": datetime(2026, 7, day, tzinfo=timezone.utc),
        }
    }


class TestSummaryArtifacts:
    """The compact card keeps the newest artifact of each (format, bom_type).

    Same key as ``Component.get_latest_sboms_by_format``, so the card and the
    release rollup agree on what "latest" means.
    """

    def test_cyclonedx_and_spdx_sboms_both_survive(self):
        """Both carry bom_type 'sbom', so keying on bom_type alone showed one."""
        summary = _summary_artifacts(
            [
                _artifact("container-cdx", "cyclonedx", "sbom", 27),
                _artifact("container-spdx", "spdx", "sbom", 26),
            ]
        )

        assert {item["sbom"]["format"] for item in summary} == {"cyclonedx", "spdx"}

    def test_newest_wins_within_one_format(self):
        summary = _summary_artifacts(
            [
                _artifact("old", "cyclonedx", "sbom", 20),
                _artifact("new", "cyclonedx", "sbom", 27),
            ]
        )

        assert [item["sbom"]["name"] for item in summary] == ["new"]

    def test_vex_and_cbom_keep_their_own_slot(self):
        """They share the cyclonedx format, so format alone would collapse them."""
        summary = _summary_artifacts(
            [
                _artifact("sbom", "cyclonedx", "sbom", 27),
                _artifact("vex", "cyclonedx", "vex", 26),
                _artifact("cbom", "cyclonedx", "cbom", 25),
            ]
        )

        assert {item["sbom"]["bom_type"] for item in summary} == {"sbom", "vex", "cbom"}

    def test_missing_bom_type_is_treated_as_sbom(self):
        """A legacy row carrying no bom_type shares the sbom slot rather than
        opening one of its own, so it cannot show up alongside its successor."""
        summary = _summary_artifacts(
            [
                _artifact("legacy", "spdx", None, 20),
                _artifact("current", "spdx", "sbom", 27),
            ]
        )

        assert [item["sbom"]["name"] for item in summary] == ["current"]
