from __future__ import annotations

import csv
import io

import pytest

from sbomify.apps.controls.models import ControlStatus
from sbomify.apps.controls.services.export_service import export_controls_csv, export_controls_summary_csv
from sbomify.apps.controls.services.status_service import upsert_status


@pytest.mark.django_db
class TestExportControlsCsv:
    def test_csv_contains_header_row(self, sample_catalog, sample_controls) -> None:
        team = sample_catalog.team
        result = export_controls_csv(team, sample_catalog)
        assert result.ok
        reader = csv.reader(io.StringIO(result.value))
        header = next(reader)
        assert header == ["Control ID", "Title", "Category", "Status", "Notes", "Last Updated"]

    def test_csv_contains_all_controls_with_statuses(self, sample_catalog, sample_controls, sample_user) -> None:
        team = sample_catalog.team
        upsert_status(sample_controls[0], None, ControlStatus.Status.COMPLIANT, sample_user, notes="done")
        upsert_status(sample_controls[1], None, ControlStatus.Status.PARTIAL, sample_user, notes="WIP")
        # sample_controls[2] has no explicit status

        result = export_controls_csv(team, sample_catalog)
        assert result.ok

        reader = csv.reader(io.StringIO(result.value))
        rows = list(reader)

        # Header + 3 controls
        assert len(rows) == 4

        # Check first control row
        row_cc61 = next(r for r in rows[1:] if r[0] == "CC6.1")
        assert row_cc61[1] == "Logical and physical access controls"
        assert row_cc61[2] == "Security"
        assert row_cc61[3] == ControlStatus.Status.COMPLIANT
        assert row_cc61[4] == "done"
        assert row_cc61[5] != ""  # Last Updated should be populated

        # Check control with partial status
        row_cc62 = next(r for r in rows[1:] if r[0] == "CC6.2")
        assert row_cc62[3] == ControlStatus.Status.PARTIAL
        assert row_cc62[4] == "WIP"

        # Check control without status
        row_cc71 = next(r for r in rows[1:] if r[0] == "CC7.1")
        assert row_cc71[3] == ControlStatus.Status.NOT_IMPLEMENTED
        assert row_cc71[5] == ""  # No Last Updated for unset status

    def test_csv_empty_catalog(self, sample_catalog) -> None:
        """A catalog with no controls should still return a header."""
        from sbomify.apps.controls.models import Control

        Control.objects.filter(catalog=sample_catalog).delete()
        team = sample_catalog.team
        result = export_controls_csv(team, sample_catalog)
        assert result.ok

        reader = csv.reader(io.StringIO(result.value))
        rows = list(reader)
        assert len(rows) == 1  # Header only
        assert rows[0][0] == "Control ID"


@pytest.mark.django_db
class TestExportControlsSummaryCsv:
    def test_summary_csv_has_category_rows(self, sample_catalog, sample_controls, sample_user) -> None:
        team = sample_catalog.team
        upsert_status(sample_controls[0], None, ControlStatus.Status.COMPLIANT, sample_user)
        upsert_status(sample_controls[1], None, ControlStatus.Status.PARTIAL, sample_user)

        result = export_controls_summary_csv(team)
        assert result.ok

        reader = csv.reader(io.StringIO(result.value))
        rows = list(reader)

        # Header + 2 categories (Security, Availability)
        assert len(rows) == 3

        header = rows[0]
        assert header == ["Category", "Total", "Compliant", "Partial", "Not Met", "N/A", "Percentage"]

        # Security: 2 controls, 1 compliant, 1 partial => 75%
        security_row = next(r for r in rows[1:] if r[0] == "Security")
        assert security_row[1] == "2"  # Total
        assert security_row[2] == "1"  # Compliant
        assert security_row[3] == "1"  # Partial
        assert security_row[6] == "75.0"  # Percentage

        # Availability: 1 control, 0 addressed => 0%
        availability_row = next(r for r in rows[1:] if r[0] == "Availability")
        assert availability_row[1] == "1"
        assert availability_row[6] == "0.0"

    def test_summary_csv_no_active_catalog(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = export_controls_summary_csv(team)
        assert result.ok
        reader = csv.reader(io.StringIO(result.value))
        rows = list(reader)
        # Should have just the header
        assert len(rows) == 1
        assert rows[0][0] == "Category"

    def test_summary_csv_with_na_controls(self, sample_catalog, sample_controls, sample_user) -> None:
        """N/A controls should be excluded from total but shown in the N/A column."""
        team = sample_catalog.team
        upsert_status(sample_controls[0], None, ControlStatus.Status.COMPLIANT, sample_user)
        upsert_status(sample_controls[1], None, ControlStatus.Status.NOT_APPLICABLE, sample_user)

        result = export_controls_summary_csv(team)
        assert result.ok

        reader = csv.reader(io.StringIO(result.value))
        rows = list(reader)

        security_row = next(r for r in rows[1:] if r[0] == "Security")
        # Total = 2 - 1 N/A = 1
        assert security_row[1] == "1"
        # N/A count
        assert security_row[5] == "1"
        # 1 compliant / 1 total = 100%
        assert security_row[6] == "100.0"
