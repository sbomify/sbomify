from __future__ import annotations

import pytest

from sbomify.apps.controls.models import ControlStatus
from sbomify.apps.controls.services.status_service import (
    bulk_update_statuses,
    get_controls_summary,
    upsert_status,
)


@pytest.mark.django_db
class TestUpsertStatus:
    def test_creates_new_status(self, sample_controls, sample_user) -> None:
        control = sample_controls[0]
        result = upsert_status(control, None, ControlStatus.Status.COMPLIANT, sample_user)
        assert result.ok
        cs = result.value
        assert cs.control == control
        assert cs.product is None
        assert cs.status == ControlStatus.Status.COMPLIANT
        assert cs.updated_by == sample_user

    def test_updates_existing_status(self, sample_controls, sample_user) -> None:
        control = sample_controls[0]
        upsert_status(control, None, ControlStatus.Status.COMPLIANT, sample_user)
        result = upsert_status(control, None, ControlStatus.Status.PARTIAL, sample_user, notes="in progress")
        assert result.ok
        assert result.value.status == ControlStatus.Status.PARTIAL
        assert result.value.notes == "in progress"
        # Should still be only one ControlStatus for this control globally
        assert ControlStatus.objects.filter(control=control, product__isnull=True).count() == 1

    def test_invalid_status_returns_failure(self, sample_controls, sample_user) -> None:
        control = sample_controls[0]
        result = upsert_status(control, None, "invalid_status", sample_user)
        assert not result.ok
        assert "Invalid status" in result.error


@pytest.mark.django_db
class TestBulkUpdateStatuses:
    def test_bulk_update_succeeds(self, sample_controls, sample_user) -> None:
        updates = [
            {"control_id": sample_controls[0].id, "status": ControlStatus.Status.COMPLIANT},
            {"control_id": sample_controls[1].id, "status": ControlStatus.Status.PARTIAL, "notes": "WIP"},
        ]
        result = bulk_update_statuses(updates, sample_user)
        assert result.ok
        assert result.value == 2
        assert ControlStatus.objects.filter(control=sample_controls[0]).first().status == ControlStatus.Status.COMPLIANT
        assert ControlStatus.objects.filter(control=sample_controls[1]).first().status == ControlStatus.Status.PARTIAL

    def test_bulk_update_is_atomic(self, sample_controls, sample_user) -> None:
        """If one update references a nonexistent control, all should roll back."""
        updates = [
            {"control_id": sample_controls[0].id, "status": ControlStatus.Status.COMPLIANT},
            {"control_id": "nonexistent_id", "status": ControlStatus.Status.COMPLIANT},
        ]
        result = bulk_update_statuses(updates, sample_user)
        assert not result.ok
        # The first update should have been rolled back
        assert not ControlStatus.objects.filter(control=sample_controls[0]).exists()

    def test_bulk_update_invalid_status_returns_failure(self, sample_controls, sample_user) -> None:
        updates = [
            {"control_id": sample_controls[0].id, "status": "bogus"},
        ]
        result = bulk_update_statuses(updates, sample_user)
        assert not result.ok
        assert "Invalid status" in result.error


@pytest.mark.django_db
class TestGetControlsSummary:
    def test_scoring_compliant_and_partial(self, sample_catalog, sample_controls, sample_user) -> None:
        """compliant=1, partial=0.5, N/A excluded from total."""
        # CC6.1 = compliant (1.0), CC6.2 = partial (0.5), CC7.1 = not_applicable (excluded)
        upsert_status(sample_controls[0], None, ControlStatus.Status.COMPLIANT, sample_user)
        upsert_status(sample_controls[1], None, ControlStatus.Status.PARTIAL, sample_user)
        upsert_status(sample_controls[2], None, ControlStatus.Status.NOT_APPLICABLE, sample_user)

        team = sample_catalog.team
        result = get_controls_summary(team)
        assert result.ok
        summary = result.value
        # Total = 3 controls - 1 N/A = 2
        assert summary["total"] == 2
        # Addressed = 1 (compliant) + 0.5 (partial) = 1.5
        assert summary["addressed"] == 1.5
        # Percentage = 1.5 / 2 * 100 = 75.0
        assert summary["percentage"] == 75.0
        assert summary["by_status"][ControlStatus.Status.COMPLIANT] == 1
        assert summary["by_status"][ControlStatus.Status.PARTIAL] == 1
        assert summary["by_status"][ControlStatus.Status.NOT_APPLICABLE] == 1

    def test_empty_statuses_returns_zero(self, sample_catalog, sample_controls) -> None:
        """No statuses at all means 0% (controls default to not_implemented)."""
        team = sample_catalog.team
        result = get_controls_summary(team)
        assert result.ok
        summary = result.value
        assert summary["total"] == 3
        assert summary["addressed"] == 0.0
        assert summary["percentage"] == 0.0

    def test_categories_breakdown(self, sample_catalog, sample_controls, sample_user) -> None:
        """Categories should list groups with per-group scoring."""
        upsert_status(sample_controls[0], None, ControlStatus.Status.COMPLIANT, sample_user)
        upsert_status(sample_controls[1], None, ControlStatus.Status.COMPLIANT, sample_user)

        team = sample_catalog.team
        result = get_controls_summary(team)
        assert result.ok
        categories = result.value["categories"]
        assert len(categories) == 2  # Security and Availability

        security = next(c for c in categories if c["name"] == "Security")
        assert security["total"] == 2
        assert security["addressed"] == 2.0
        assert security["percentage"] == 100.0

        availability = next(c for c in categories if c["name"] == "Availability")
        assert availability["total"] == 1
        assert availability["addressed"] == 0.0
        assert availability["percentage"] == 0.0

    def test_no_active_catalog_returns_empty(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = get_controls_summary(team)
        assert result.ok
        assert result.value["total"] == 0
        assert result.value["percentage"] == 0.0
