from __future__ import annotations

import pytest

from sbomify.apps.controls.models import Control, ControlCatalog, ControlMapping
from sbomify.apps.controls.services.mapping_service import (
    create_mapping,
    get_mappings_for_control,
    import_mappings_bulk,
)


@pytest.fixture
def second_catalog(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return ControlCatalog.objects.create(
        team=team, name="ISO 27001", version="2022", source=ControlCatalog.Source.BUILTIN
    )


@pytest.fixture
def iso_controls(second_catalog):
    controls = []
    for i, (cid, title, group) in enumerate(
        [
            ("A.8.1", "Asset management", "Asset Management"),
            ("A.9.1", "Access control policy", "Access Control"),
        ]
    ):
        controls.append(
            Control.objects.create(catalog=second_catalog, group=group, control_id=cid, title=title, sort_order=i)
        )
    return controls


@pytest.mark.django_db
class TestCreateMapping:
    def test_creates_mapping_between_catalogs(self, sample_controls, iso_controls) -> None:
        result = create_mapping(sample_controls[0], iso_controls[0], "equivalent")
        assert result.ok
        mapping = result.value
        assert mapping is not None
        assert mapping.source_control_id == sample_controls[0].id
        assert mapping.target_control_id == iso_controls[0].id
        assert mapping.relation_type == "equivalent"

    def test_creates_mapping_with_notes(self, sample_controls, iso_controls) -> None:
        result = create_mapping(sample_controls[0], iso_controls[0], "partial", notes="Partial overlap in scope")
        assert result.ok
        assert result.value is not None
        assert result.value.notes == "Partial overlap in scope"

    def test_rejects_self_mapping(self, sample_controls) -> None:
        result = create_mapping(sample_controls[0], sample_controls[0], "equivalent")
        assert not result.ok
        assert result.status_code == 400
        assert "itself" in (result.error or "").lower()

    def test_rejects_same_catalog_mapping(self, sample_controls) -> None:
        result = create_mapping(sample_controls[0], sample_controls[1], "related")
        assert not result.ok
        assert result.status_code == 400
        assert "same catalog" in (result.error or "").lower()

    def test_rejects_invalid_relation_type(self, sample_controls, iso_controls) -> None:
        result = create_mapping(sample_controls[0], iso_controls[0], "bogus")
        assert not result.ok
        assert result.status_code == 400

    def test_rejects_duplicate_mapping(self, sample_controls, iso_controls) -> None:
        create_mapping(sample_controls[0], iso_controls[0], "equivalent")
        result = create_mapping(sample_controls[0], iso_controls[0], "partial")
        assert not result.ok
        assert result.status_code == 409


@pytest.mark.django_db
class TestGetMappingsForControl:
    def test_returns_mappings_as_source(self, sample_controls, iso_controls) -> None:
        create_mapping(sample_controls[0], iso_controls[0], "equivalent")
        result = get_mappings_for_control(sample_controls[0])
        assert result.ok
        assert result.value is not None
        assert len(result.value) == 1

    def test_returns_mappings_as_target(self, sample_controls, iso_controls) -> None:
        create_mapping(sample_controls[0], iso_controls[0], "equivalent")
        result = get_mappings_for_control(iso_controls[0])
        assert result.ok
        assert result.value is not None
        assert len(result.value) == 1

    def test_returns_both_directions(self, sample_controls, iso_controls) -> None:
        create_mapping(sample_controls[0], iso_controls[0], "equivalent")
        create_mapping(iso_controls[1], sample_controls[0], "related")
        result = get_mappings_for_control(sample_controls[0])
        assert result.ok
        assert result.value is not None
        assert len(result.value) == 2

    def test_returns_empty_list_when_no_mappings(self, sample_controls) -> None:
        result = get_mappings_for_control(sample_controls[0])
        assert result.ok
        assert result.value is not None
        assert len(result.value) == 0


@pytest.mark.django_db
class TestImportMappingsBulk:
    def test_imports_valid_mappings(self, sample_controls, iso_controls, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        items = [
            {
                "source_control_id": sample_controls[0].id,
                "target_control_id": iso_controls[0].id,
                "relation_type": "equivalent",
            },
            {
                "source_control_id": sample_controls[1].id,
                "target_control_id": iso_controls[1].id,
                "relation_type": "partial",
                "notes": "Overlapping scope",
            },
        ]
        result = import_mappings_bulk(items, team)
        assert result.ok
        assert result.value == 2
        assert ControlMapping.objects.count() == 2

    def test_rejects_empty_list(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = import_mappings_bulk([], team)
        assert not result.ok
        assert result.status_code == 400

    def test_rejects_over_limit(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        items = [{"source_control_id": "a", "target_control_id": "b", "relation_type": "equivalent"}] * 501
        result = import_mappings_bulk(items, team)
        assert not result.ok
        assert result.status_code == 400
        assert "500" in (result.error or "")

    def test_skips_invalid_items_but_imports_valid(
        self, sample_controls, iso_controls, sample_team_with_owner_member
    ) -> None:
        team = sample_team_with_owner_member.team
        items = [
            {
                "source_control_id": sample_controls[0].id,
                "target_control_id": iso_controls[0].id,
                "relation_type": "equivalent",
            },
            {
                "source_control_id": "nonexistent",
                "target_control_id": iso_controls[1].id,
                "relation_type": "related",
            },
        ]
        result = import_mappings_bulk(items, team)
        assert result.ok
        assert result.value == 1

    def test_rejects_all_invalid_items(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        items = [
            {
                "source_control_id": "nonexistent1",
                "target_control_id": "nonexistent2",
                "relation_type": "equivalent",
            },
        ]
        result = import_mappings_bulk(items, team)
        assert not result.ok
        assert result.status_code == 400

    def test_ignores_duplicate_conflicts(self, sample_controls, iso_controls, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        create_mapping(sample_controls[0], iso_controls[0], "equivalent")
        items = [
            {
                "source_control_id": sample_controls[0].id,
                "target_control_id": iso_controls[0].id,
                "relation_type": "partial",
            },
        ]
        result = import_mappings_bulk(items, team)
        assert result.ok
        # Duplicate was ignored, so still only one mapping exists
        assert ControlMapping.objects.count() == 1
