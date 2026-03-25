from __future__ import annotations

import pytest

from sbomify.apps.controls.models import Control, ControlCatalog
from sbomify.apps.controls.services.catalog_service import (
    activate_builtin_catalog,
    delete_catalog,
    get_active_catalogs,
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
