from __future__ import annotations

import pytest

from sbomify.apps.controls.models import Control, ControlCatalog
from sbomify.apps.controls.services.catalog_service import (
    activate_builtin_catalog,
    delete_catalog,
    get_active_catalogs,
    import_oscal_catalog,
)
from sbomify.apps.teams.models import Team
from sbomify.apps.teams.utils import number_to_random_token


@pytest.mark.django_db
class TestActivateBuiltinCatalog:
    def test_creates_catalog_and_controls(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = activate_builtin_catalog(team, "soc2-type2")
        assert result.ok
        catalog = result.value
        assert catalog is not None
        assert catalog.name == "SOC 2 Type II"
        assert catalog.source == ControlCatalog.Source.BUILTIN
        assert catalog.controls.count() > 0

    def test_duplicate_activation_returns_existing(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        r1 = activate_builtin_catalog(team, "soc2-type2")
        r2 = activate_builtin_catalog(team, "soc2-type2")
        assert r1.ok and r2.ok
        assert r1.value is not None and r2.value is not None
        assert r1.value.id == r2.value.id
        # Controls should not be duplicated
        assert Control.objects.filter(catalog=r2.value).count() == Control.objects.filter(catalog=r1.value).count()

    def test_reactivates_inactive_catalog(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        r1 = activate_builtin_catalog(team, "soc2-type2")
        assert r1.ok and r1.value is not None
        # Deactivate
        r1.value.is_active = False
        r1.value.save(update_fields=["is_active"])
        # Re-activate
        r2 = activate_builtin_catalog(team, "soc2-type2")
        assert r2.ok and r2.value is not None
        assert r2.value.id == r1.value.id
        assert r2.value.is_active is True

    def test_unknown_catalog_returns_failure(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = activate_builtin_catalog(team, "nonexistent")
        assert not result.ok
        assert result.status_code == 404


@pytest.mark.django_db
class TestGetActiveCatalogs:
    def test_returns_active_only(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        activate_builtin_catalog(team, "soc2-type2")
        result = get_active_catalogs(team)
        assert result.ok
        assert result.value is not None
        assert len(result.value) == 1

    def test_excludes_inactive_catalogs(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        r = activate_builtin_catalog(team, "soc2-type2")
        assert r.ok and r.value is not None
        r.value.is_active = False
        r.value.save(update_fields=["is_active"])
        result = get_active_catalogs(team)
        assert result.ok
        assert result.value is not None
        assert len(result.value) == 0

    def test_empty_when_none_active(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = get_active_catalogs(team)
        assert result.ok
        assert result.value is not None
        assert len(result.value) == 0


@pytest.mark.django_db
class TestDeleteCatalog:
    def test_deletes_catalog_and_controls(self, sample_catalog) -> None:
        catalog_id = sample_catalog.id
        result = delete_catalog(catalog_id, sample_catalog.team)
        assert result.ok
        assert not ControlCatalog.objects.filter(id=catalog_id).exists()

    def test_wrong_team_returns_failure(self, sample_catalog) -> None:
        other_team = Team.objects.create(name="other team")
        other_team.key = number_to_random_token(other_team.pk)
        other_team.save()
        result = delete_catalog(sample_catalog.id, other_team)
        assert not result.ok
        assert result.status_code == 404

    def test_nonexistent_catalog_returns_failure(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = delete_catalog("nonexistent_id", team)
        assert not result.ok
        assert result.status_code == 404


SAMPLE_OSCAL_CATALOG = {
    "catalog": {
        "uuid": "test-uuid-1234",
        "metadata": {
            "title": "Test OSCAL Catalog",
            "version": "1.0",
            "oscal-version": "1.1.0",
        },
        "groups": [
            {
                "id": "ac",
                "title": "Access Control",
                "controls": [
                    {
                        "id": "ac-1",
                        "title": "Policy and Procedures",
                        "parts": [
                            {
                                "id": "ac-1_smt",
                                "name": "statement",
                                "prose": "Develop and maintain access control policies.",
                            }
                        ],
                        "controls": [
                            {
                                "id": "ac-1.1",
                                "title": "Automation Support",
                                "parts": [
                                    {
                                        "id": "ac-1.1_smt",
                                        "name": "statement",
                                        "prose": "Automate access control policy enforcement.",
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "id": "ac-2",
                        "title": "Account Management",
                    },
                ],
            },
            {
                "id": "au",
                "title": "Audit and Accountability",
                "controls": [
                    {
                        "id": "au-1",
                        "title": "Audit Policy and Procedures",
                    },
                ],
            },
        ],
    }
}


@pytest.mark.django_db
class TestImportOscalCatalog:
    def test_imports_valid_oscal_catalog(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = import_oscal_catalog(team, SAMPLE_OSCAL_CATALOG)
        assert result.ok
        catalog = result.value
        assert catalog is not None
        assert catalog.name == "Test OSCAL Catalog"
        assert catalog.version == "1.0"
        assert catalog.source == ControlCatalog.Source.CUSTOM
        # 3 controls + 1 sub-control = 4
        assert Control.objects.filter(catalog=catalog).count() == 4

    def test_imports_sub_controls(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = import_oscal_catalog(team, SAMPLE_OSCAL_CATALOG)
        assert result.ok
        catalog = result.value
        assert catalog is not None
        assert Control.objects.filter(catalog=catalog, control_id="ac-1.1").exists()

    def test_extracts_description_from_parts(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = import_oscal_catalog(team, SAMPLE_OSCAL_CATALOG)
        assert result.ok
        control = Control.objects.get(catalog=result.value, control_id="ac-1")
        assert "access control policies" in control.description

    def test_preserves_group_names(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = import_oscal_catalog(team, SAMPLE_OSCAL_CATALOG)
        assert result.ok
        groups = set(Control.objects.filter(catalog=result.value).values_list("group", flat=True))
        assert groups == {"Access Control", "Audit and Accountability"}

    def test_rejects_missing_catalog_key(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = import_oscal_catalog(team, {"not_catalog": {}})
        assert not result.ok
        assert result.status_code == 400

    def test_rejects_missing_metadata(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = import_oscal_catalog(team, {"catalog": {"groups": []}})
        assert not result.ok
        assert result.status_code == 400

    def test_rejects_empty_groups(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        result = import_oscal_catalog(team, {
            "catalog": {"metadata": {"title": "Empty"}, "groups": []}
        })
        assert not result.ok
        assert result.status_code == 400

    def test_rejects_duplicate_catalog(self, sample_team_with_owner_member) -> None:
        team = sample_team_with_owner_member.team
        import_oscal_catalog(team, SAMPLE_OSCAL_CATALOG)
        result = import_oscal_catalog(team, SAMPLE_OSCAL_CATALOG)
        assert not result.ok
        assert result.status_code == 409


@pytest.mark.django_db
class TestBuiltinCatalogData:
    """The data directory is glob-registered, so a bad file ships silently.

    ``_BUILTIN_CATALOGS`` picks up whatever ``*.json`` is present, and nothing
    reads those files until a customer activates one. A malformed or empty
    catalogue would therefore first surface as a failed activation in
    production rather than at CI.
    """

    def test_every_builtin_catalogue_is_well_formed(self) -> None:
        import json

        from sbomify.apps.controls.services.catalog_service import _BUILTIN_CATALOGS, _DATA_DIR

        assert _BUILTIN_CATALOGS, "no built-in catalogues were discovered"

        for slug, filename in _BUILTIN_CATALOGS.items():
            data = json.loads((_DATA_DIR / filename).read_text(encoding="utf-8"))
            assert data.get("name"), f"{slug}: missing name"
            assert data.get("version"), f"{slug}: missing version"
            assert data.get("groups"), f"{slug}: no groups"

            seen: set[str] = set()
            for group in data["groups"]:
                assert group.get("name"), f"{slug}: a group has no name"
                assert group.get("controls"), f"{slug}: group {group.get('name')!r} has no controls"
                for control in group["controls"]:
                    control_id = control.get("control_id")
                    assert control_id, f"{slug}: a control in {group['name']!r} has no id"
                    assert control_id not in seen, f"{slug}: duplicate control {control_id}"
                    seen.add(control_id)
                    assert control.get("title"), f"{slug}: control {control_id} has no title"

    def test_800_171_carries_all_110_requirements(self, sample_team_with_owner_member) -> None:
        """Rev. 2 is 110 requirements over 14 families, and CMMC L2 is the same set.

        The two catalogues are the same requirements under different
        identifiers — ``3.1.1`` here, ``AC.L2-3.1.1`` there — so if they ever
        stop agreeing, one of them has been edited in isolation.
        """
        team = sample_team_with_owner_member.team

        result = activate_builtin_catalog(team, "nist-800-171-r2")
        assert result.ok
        catalog = result.value
        assert catalog is not None
        assert catalog.name == "NIST SP 800-171"
        assert catalog.version == "Rev. 2"
        assert catalog.controls.count() == 110
        assert catalog.controls.values("group").distinct().count() == 14

        cmmc = activate_builtin_catalog(team, "cmmc-2")
        assert cmmc.ok and cmmc.value is not None
        derived = {cid.split("-", 1)[1] for cid in cmmc.value.controls.values_list("control_id", flat=True)}
        assert derived == set(catalog.controls.values_list("control_id", flat=True))


def test_every_builtin_catalogue_has_a_tile_in_settings() -> None:
    """The catalogue tiles are hand-kept; the catalogues themselves are globbed.

    Dropping a file into ``controls/data`` registers it for the API but not for
    the UI, so a catalogue can ship fully working and be unreachable for every
    admin — which is exactly what happened to NIST SP 800-171. Comparing the two
    lists is the only thing that notices.
    """
    from sbomify.apps.controls.services.catalog_service import _BUILTIN_CATALOGS
    from sbomify.apps.teams.views.team_settings import BUILTIN_CATALOG_TILES

    tiles = {slug for slug, _name, _label, _icon in BUILTIN_CATALOG_TILES}

    assert tiles == set(_BUILTIN_CATALOGS), (
        f"catalogues with no tile: {sorted(set(_BUILTIN_CATALOGS) - tiles)}; "
        f"tiles with no catalogue: {sorted(tiles - set(_BUILTIN_CATALOGS))}"
    )
