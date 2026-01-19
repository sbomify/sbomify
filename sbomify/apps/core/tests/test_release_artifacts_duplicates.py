"""Tests for duplicate artifacts in release page (Issue #506)."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import Component, Product, Project, Release
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.core.tests.shared_fixtures import get_api_headers
from sbomify.apps.sboms.models import SBOM
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_access_token,
    sample_billing_plan,
    sample_component,
    sample_product,
    sample_project,
)
from sbomify.apps.teams.fixtures import sample_team_with_owner_member  # noqa: F401
from sbomify.apps.teams.models import Member


@pytest.mark.django_db
def test_no_duplicate_artifacts_when_component_in_multiple_projects(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    sample_billing_plan,  # noqa: F811
):
    """Test that components shared across multiple projects don't cause duplicate artifacts.
    
    This test reproduces and validates the fix for Issue #506 where artifacts were appearing
    multiple times in the release page when a component was associated with multiple projects
    that all belonged to the same product.
    
    The bug was caused by using .distinct() on a queryset that traversed many-to-many 
    relationships with models having default ordering. PostgreSQL's DISTINCT ON requires
    the ORDER BY clause to match the DISTINCT ON expressions.
    """
    client = Client()
    team = sample_team_with_owner_member.team
    
    # Set up billing plan
    team.billing_plan = sample_billing_plan.key
    team.save()
    
    # Create a product
    product = Product.objects.create(
        team=team,
        name="Test Product",
        is_public=True,
    )
    
    # Create multiple projects for the same product
    project1 = Project.objects.create(
        team=team,
        name="Project 1",
        is_public=True,
    )
    project2 = Project.objects.create(
        team=team,
        name="Project 2",
        is_public=True,
    )
    
    # Link both projects to the product
    product.projects.add(project1, project2)
    
    # Create a component that belongs to BOTH projects
    component = Component.objects.create(
        team=team,
        name="Shared Component",
        component_type="library",
        visibility=Component.Visibility.PUBLIC,
    )
    
    # Add component to both projects (this is the key setup that triggers the bug)
    project1.components.add(component)
    project2.components.add(component)
    
    # Create an SBOM for the component
    sbom = SBOM.objects.create(
        component=component,
        format="cyclonedx",
        format_version="1.4",
        name=f"{component.name} SBOM",
        version="1.0.0",
    )
    
    # Create a release for the product
    release = Release.objects.create(
        product=product,
        name="v1.0.0",
        description="Test release",
    )
    
    # Call the API that was showing duplicates
    url = reverse("api-1:list_release_artifacts", kwargs={"release_id": release.id})
    response = client.get(
        url,
        {"mode": "available"},
        **get_api_headers(sample_access_token),
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # The critical assertion: even though the component is in 2 projects,
    # the SBOM should appear only ONCE in the available artifacts list
    assert len(data["items"]) == 1, (
        f"Expected 1 artifact but got {len(data['items'])}. "
        "This indicates the duplicate artifacts bug is present."
    )
    
    # Verify it's the correct artifact
    artifact = data["items"][0]
    assert artifact["id"] == sbom.id
    assert artifact["component"]["id"] == component.id


@pytest.mark.django_db
def test_distinct_queries_in_models(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_billing_plan,  # noqa: F811
):
    """Test that Component.get_products() and Release.refresh_latest_artifacts() work correctly.
    
    These methods use .distinct() on querysets with many-to-many relationships and were
    identified as having the same potential issue as the API endpoint.
    """
    team = sample_team_with_owner_member.team
    team.billing_plan = sample_billing_plan.key
    team.save()
    
    # Create a product
    product = Product.objects.create(
        team=team,
        name="Test Product",
    )
    
    # Create multiple projects
    project1 = Project.objects.create(team=team, name="Project 1")
    project2 = Project.objects.create(team=team, name="Project 2")
    
    # Link projects to product
    product.projects.add(project1, project2)
    
    # Create a component in both projects
    component = Component.objects.create(
        team=team,
        name="Test Component",
        component_type="library",
    )
    project1.components.add(component)
    project2.components.add(component)
    
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
def test_multiple_components_multiple_projects_no_duplicates(
    sample_team_with_owner_member: Member,  # noqa: F811
    sample_access_token: AccessToken,  # noqa: F811
    sample_billing_plan,  # noqa: F811
):
    """Test complex scenario with multiple components and projects.
    
    This test ensures the fix works correctly even with a more complex graph of
    components, projects, and products.
    """
    client = Client()
    team = sample_team_with_owner_member.team
    team.billing_plan = sample_billing_plan.key
    team.save()
    
    # Create a product
    product = Product.objects.create(team=team, name="Complex Product", is_public=True)
    
    # Create 3 projects
    projects = [
        Project.objects.create(team=team, name=f"Project {i}", is_public=True)
        for i in range(1, 4)
    ]
    for project in projects:
        product.projects.add(project)
    
    # Create 2 components
    components = [
        Component.objects.create(
            team=team,
            name=f"Component {i}",
            component_type="library",
            visibility=Component.Visibility.PUBLIC,
        )
        for i in range(1, 3)
    ]
    
    # Component 1 is in all 3 projects (most likely to cause duplicates)
    for project in projects:
        project.components.add(components[0])
    
    # Component 2 is in 2 projects
    projects[0].components.add(components[1])
    projects[1].components.add(components[1])
    
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
        f"Expected 2 artifacts but got {len(data['items'])}. "
        "Components shared across multiple projects are causing duplicates."
    )
    
    # Verify we have the correct unique artifacts
    artifact_ids = {artifact["id"] for artifact in data["items"]}
    expected_ids = {sbom.id for sbom in sboms}
    assert artifact_ids == expected_ids, "Artifacts don't match expected SBOMs"
