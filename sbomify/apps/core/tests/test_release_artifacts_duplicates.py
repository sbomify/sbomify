"""Tests for duplicate artifacts in release page (Issue #506)."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import Component, Product, Release
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_access_token,
    sample_billing_plan,
    sample_component,
    sample_product,
)
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import Member


@pytest.mark.django_db
def test_distinct_queries_in_models(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_billing_plan,  # noqa: F811
):
    """Test that Component.get_products() and Release.refresh_latest_artifacts() work correctly.

    These methods use .distinct() on querysets with many-to-many relationships. With direct
    ProductComponent M2M, the same component attached to a single product should still produce
    a single, deduplicated result.
    """
    team = sample_team_with_owner_member.team
    team.billing_plan = sample_billing_plan.key
    team.save()

    # Create a product
    product = Product.objects.create(
        team=team,
        name="Test Product",
    )

    # Create a component and attach it to the product
    component = Component.objects.create(
        team=team,
        name="Test Component",
        component_type="bom",
    )
    product.components.add(component)

    # Test Component.get_products() - should return product only once
    products = list(component.get_products())
    assert len(products) == 1, f"Expected 1 product but got {len(products)}"
    assert products[0].id == product.id

    # Create SBOM for the component
    sbom = SBOM.objects.create(
        component=component,
        format="cyclonedx",
        format_version="1.4",
        name=f"{component.name} SBOM",
        version="1.0.0",
    )

    # Create and test latest release refresh
    latest_release = Release.get_or_create_latest_release(product)
    latest_release.refresh_latest_artifacts()

    # Should have exactly one artifact (not duplicated)
    artifacts = list(latest_release.artifacts.all())
    assert len(artifacts) == 1, f"Expected 1 artifact but got {len(artifacts)}"
    assert artifacts[0].sbom_id == sbom.id


@pytest.mark.django_db
def test_multiple_components_no_duplicates(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    sample_billing_plan,  # noqa: F811
):
    """Test that multiple components attached to a product don't produce duplicate artifacts.

    Ensures the available-artifact listing returns each artifact exactly once per component.
    """
    client = Client()
    team = sample_team_with_owner_member.team
    team.billing_plan = sample_billing_plan.key
    team.save()

    # Create a product
    product = Product.objects.create(team=team, name="Complex Product", is_public=True)

    # Create 2 components and attach them to the product
    components = [
        Component.objects.create(
            team=team,
            name=f"Component {i}",
            component_type="bom",
            visibility=Component.Visibility.PUBLIC,
        )
        for i in range(1, 3)
    ]
    for component in components:
        product.components.add(component)

    # Create SBOMs for both components
    sboms = []
    for i, component in enumerate(components):
        sbom = SBOM.objects.create(
            component=component,
            format="cyclonedx",
            format_version=f"1.{4+i}",
            name=f"{component.name} SBOM",
            version="1.0.0",
        )
        sboms.append(sbom)

    # Create a release
    release = Release.objects.create(
        product=product,
        name="v2.0.0",
        description="Complex test release",
    )

    # Call the API
    url = reverse("api-1:list_release_artifacts", kwargs={"release_id": release.id})
    response = client.get(
        url,
        {"mode": "available"},
        **get_api_headers(sample_access_token),
    )

    assert response.status_code == 200
    data = response.json()

    # Should have exactly 2 artifacts (one per component), no duplicates
    assert len(data["items"]) == 2, (
        f"Expected 2 artifacts but got {len(data['items'])}. Components are producing duplicates."
    )

    # Verify we have the correct unique artifacts
    artifact_ids = {artifact["id"] for artifact in data["items"]}
    expected_ids = {sbom.id for sbom in sboms}
    assert artifact_ids == expected_ids, "Artifacts don't match expected SBOMs"


@pytest.mark.django_db
def test_component_in_multiple_products_returns_distinct_products(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_billing_plan,  # noqa: F811
):
    """Component.get_products() should return each product exactly once even when shared.

    With direct ProductComponent M2M a component can be attached to multiple products.
    Ensure the helper still deduplicates the listing.
    """
    team = sample_team_with_owner_member.team
    team.billing_plan = sample_billing_plan.key
    team.save()

    product1 = Product.objects.create(team=team, name="Product One")
    product2 = Product.objects.create(team=team, name="Product Two")

    component = Component.objects.create(
        team=team,
        name="Shared Component",
        component_type="bom",
    )
    product1.components.add(component)
    product2.components.add(component)

    products = list(component.get_products())
    product_ids = sorted(p.id for p in products)
    expected_ids = sorted([product1.id, product2.id])
    assert product_ids == expected_ids, "Component.get_products() did not return distinct products"
