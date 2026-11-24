"""A TEA subscription holds no SBOMs of its own, so the places built for them leave it out."""

from __future__ import annotations

import json

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.compliance.services.sbom_compliance_service import get_bsi_assessment_status
from sbomify.apps.core.models import Component, Product
from sbomify.apps.core.queries import get_team_asset_count, get_team_asset_counts
from sbomify.apps.core.services.inventory_page import build_inventory_snapshot
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.core.views.product_details_public import _prepare_public_components
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def mixed(sample_team, make_subscription):
    """A product with one ordinary BOM component and one subscription."""
    bom = Component.objects.create(team=sample_team, name="ours", visibility=Component.Visibility.PUBLIC)
    subscription = make_subscription(sample_team, name="theirs")
    product = Product.objects.create(team=sample_team, name="product", is_public=True)
    product.components.add(bom, subscription.component)
    return sample_team, product, bom, subscription.component


def test_a_subscription_does_not_count_toward_plan_limits(mixed):
    team = mixed[0]

    assert get_team_asset_count(str(team.id), "component") == 1
    assert get_team_asset_counts(str(team.id))["components"] == 1


def test_sbom_uploads_to_a_subscription_are_refused(
    sample_team_with_owner_member, authenticated_api_client, make_subscription  # noqa: F811
):
    client, token = authenticated_api_client
    component = make_subscription(sample_team_with_owner_member.team).component

    response = client.post(
        f"/api/v1/sboms/artifact/cyclonedx/{component.id}",
        data=json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6"}),
        content_type="application/json",
        **get_api_headers(token),
    )

    assert response.status_code == 400
    assert "holds no uploads" in response.json()["detail"]


def test_inventory_treats_a_subscription_as_holding_no_sboms(mixed):
    team, _, bom, subscription = mixed

    rows = {row["id"]: row for row in build_inventory_snapshot(team, "components")["rows"]}

    assert rows[subscription.id]["security_applicable"] is False
    assert rows[subscription.id]["missing_sboms"] == 0
    assert rows[bom.id]["missing_sboms"] == 1


def test_cra_assesses_only_the_products_own_components(mixed):
    _, product, bom, _ = mixed

    status = get_bsi_assessment_status(product).value

    assert status["summary"]["total_components"] == 1


def test_the_trust_center_does_not_republish_a_subscription(mixed):
    team, product, bom, subscription = mixed
    team.is_public = True
    team.save()

    listed = [c["id"] for c in _prepare_public_components(product.id, is_custom_domain=False)]
    page = Client().get(reverse("core:component_details_public", args=[subscription.id]))

    assert listed == [bom.id]
    assert page.status_code == 404
