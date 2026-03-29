from __future__ import annotations

import pytest

from sbomify.apps.controls.models import Control, ControlCatalog


@pytest.fixture
def sample_catalog(sample_team_with_owner_member):
    team = sample_team_with_owner_member.team
    return ControlCatalog.objects.create(
        team=team, name="SOC 2 Type II", version="2024", source=ControlCatalog.Source.BUILTIN
    )


@pytest.fixture
def sample_controls(sample_catalog):
    controls = []
    for i, (cid, title, group) in enumerate([
        ("CC6.1", "Logical and physical access controls", "Security"),
        ("CC6.2", "System credentials management", "Security"),
        ("CC7.1", "Detection and monitoring of threats", "Availability"),
    ]):
        controls.append(
            Control.objects.create(
                catalog=sample_catalog, group=group, control_id=cid, title=title, sort_order=i
            )
        )
    return controls
