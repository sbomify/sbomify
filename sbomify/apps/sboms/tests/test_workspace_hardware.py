"""The workspace hardware rollup: grouping, concentration, and flat queries."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.core.cache import cache as django_cache

from sbomify.apps.core.models import Component, Product
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.services.hardware_dashboard import build_workspace_hardware_rollup


def _hbom(parts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "metadata": {"component": {"type": "device", "name": "board"}},
        "components": [{"type": "device", **part} for part in parts],
    }


@pytest.fixture(autouse=True)
def _clear_cache():
    django_cache.clear()
    yield
    django_cache.clear()


@pytest.fixture
def hardware_workspace(sample_team_with_owner_member, monkeypatch):
    team = sample_team_with_owner_member.team
    product_a = Product.objects.create(name="Router", team=team)
    product_b = Product.objects.create(name="Switch", team=team)

    docs: dict[str, dict[str, Any]] = {}

    def component_with_hbom(name: str, product: Product, parts: list[dict[str, Any]]) -> Component:
        component = Component.objects.create(name=name, team=team)
        component.products.add(product)
        sbom = SBOM.objects.create(
            name=name,
            version="1.0",
            format="cyclonedx",
            format_version="1.6",
            sbom_filename=f"{name}.json",
            component=component,
            bom_type=SBOM.BomType.HBOM,
        )
        docs[f"{name}.json"] = _hbom(parts)
        return component

    shared_part = {"name": "STM32F407", "manufacturer": {"name": "STMicroelectronics"}}
    component_with_hbom(
        "router-board", product_a, [shared_part, {"name": "RTL8211", "manufacturer": {"name": "Realtek"}}]
    )
    component_with_hbom("switch-board", product_b, [shared_part])

    from sbomify.apps.sboms.services import hardware_dashboard

    class FakeS3:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_sbom_data(self, filename: str) -> bytes:
            return json.dumps(docs[filename]).encode()

    monkeypatch.setattr(hardware_dashboard, "S3Client", FakeS3)
    return team


@pytest.mark.django_db
class TestRollup:
    def test_parts_group_by_manufacturer_and_name(self, hardware_workspace):
        rollup = build_workspace_hardware_rollup(hardware_workspace.id)
        assert rollup["components_with_hardware"] == 2
        names = [(row["manufacturer"], row["name"]) for row in rollup["rows"]]
        assert ("STMicroelectronics", "STM32F407") in names
        assert ("Realtek", "RTL8211") in names
        assert rollup["distinct_parts"] == 2

    def test_part_in_two_products_is_flagged_and_leads(self, hardware_workspace):
        rollup = build_workspace_hardware_rollup(hardware_workspace.id)
        first = rollup["rows"][0]
        assert first["name"] == "STM32F407"
        assert first["shared"] is True
        assert first["products"] == ["Router", "Switch"]
        assert rollup["shared_parts"] == 1
        single = next(row for row in rollup["rows"] if row["name"] == "RTL8211")
        assert single["shared"] is False

    def test_query_count_stays_flat_as_components_grow(self, hardware_workspace, django_assert_max_num_queries):
        from sbomify.apps.sboms.services import hardware_dashboard

        product = Product.objects.get(name="Router", team=hardware_workspace)
        for index in range(5):
            component = Component.objects.create(name=f"extra-{index}", team=hardware_workspace)
            component.products.add(product)
            SBOM.objects.create(
                name=f"extra-{index}",
                version="1.0",
                format="cyclonedx",
                format_version="1.6",
                sbom_filename="router-board.json",
                component=component,
                bom_type=SBOM.BomType.HBOM,
            )
        django_cache.clear()
        with django_assert_max_num_queries(6):
            build_workspace_hardware_rollup(hardware_workspace.id)


@pytest.mark.django_db
class TestView:
    def test_owner_sees_the_rollup(self, hardware_workspace, authenticated_web_client, sample_user):
        from sbomify.apps.core.tests.shared_fixtures import setup_authenticated_client_session

        setup_authenticated_client_session(authenticated_web_client, hardware_workspace, sample_user)
        response = authenticated_web_client.get(f"/workspaces/{hardware_workspace.key}/hardware/")
        assert response.status_code == 200
        body = response.content.decode()
        assert "STM32F407" in body
        assert "shared" in body

    def test_non_member_is_refused(self, hardware_workspace, guest_user, client):
        client.force_login(guest_user)
        response = client.get(f"/workspaces/{hardware_workspace.key}/hardware/")
        assert response.status_code == 403
