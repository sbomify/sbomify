"""What a synced framework looks like on the public trust center."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.controls.models import Control, ControlCatalog, ControlStatus
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def public_team(sample_team_with_owner_member):  # noqa: F811
    team = sample_team_with_owner_member.team
    team.is_public = True
    team.save()
    return team


def _framework(team, *, source: str, is_active: bool = True) -> ControlCatalog:
    catalog = ControlCatalog.objects.create(
        team=team,
        name="SOC 2 Type II",
        version="" if source == ControlCatalog.Source.VANTA else "2024",
        source=source,
        external_id="fw_soc2" if source == ControlCatalog.Source.VANTA else "",
        is_active=is_active,
    )
    met = Control.objects.create(
        catalog=catalog, group="Security", control_id="CC1.1", title="Control environment", sort_order=0
    )
    Control.objects.create(
        catalog=catalog, group="Security", control_id="CC1.2", title="Board oversight", sort_order=1
    )
    ControlStatus.objects.create(control=met, product=None, status=ControlStatus.Status.COMPLIANT)
    return catalog


def _page(team) -> bytes:
    response = Client().get(reverse("core:workspace_public", kwargs={"workspace_key": team.key}))
    assert response.status_code == 200
    return response.content


class TestFrameworksSection:
    def test_a_workspace_with_no_frameworks_shows_no_section(self, public_team) -> None:
        """An empty section at the top of a trust center announces an absence."""
        assert b"Compliance frameworks" not in _page(public_team)

    def test_a_published_framework_shows_its_score(self, public_team) -> None:
        _framework(public_team, source=ControlCatalog.Source.VANTA)

        content = _page(public_team)

        assert b"Compliance frameworks" in content
        assert b"SOC 2 Type II" in content
        # One of two controls met.
        assert b"50%" in content

    def test_a_synced_framework_says_where_it_comes_from(self, public_team) -> None:
        _framework(public_team, source=ControlCatalog.Source.VANTA)

        assert b"Synced from Vanta" in _page(public_team)

    def test_a_hand_maintained_framework_claims_no_source(self, public_team) -> None:
        _framework(public_team, source=ControlCatalog.Source.BUILTIN)

        content = _page(public_team)

        assert b"SOC 2 Type II" in content
        assert b"Synced from" not in content

    def test_an_unpublished_framework_stays_off_the_page(self, public_team) -> None:
        _framework(public_team, source=ControlCatalog.Source.VANTA, is_active=False)

        assert b"Compliance frameworks" not in _page(public_team)

    def test_the_domain_breakdown_is_listed(self, public_team) -> None:
        _framework(public_team, source=ControlCatalog.Source.VANTA)

        assert b"Security" in _page(public_team)

    def test_a_fully_addressed_domain_is_marked(self, public_team) -> None:
        catalog = ControlCatalog.objects.create(
            team=public_team,
            name="ISO 27001",
            version="",
            source=ControlCatalog.Source.VANTA,
            external_id="fw_iso",
            is_active=True,
        )
        control = Control.objects.create(
            catalog=catalog, group="People Controls", control_id="A.6.1", title="Screening", sort_order=0
        )
        ControlStatus.objects.create(control=control, product=None, status=ControlStatus.Status.COMPLIANT)

        assert b"Fully addressed" in _page(public_team)
