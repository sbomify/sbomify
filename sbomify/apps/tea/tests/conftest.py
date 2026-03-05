import pytest

from sbomify.apps.core.models import Component, Release, ReleaseArtifact
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_billing_plan,
    sample_component,
    sample_product,
    sample_project,
    sample_sbom,
)
from sbomify.apps.teams.fixtures import sample_team  # noqa: F401


@pytest.fixture
def tea_enabled_product(sample_product):
    """Product with TEA enabled on its team."""
    sample_product.is_public = True
    sample_product.save()
    sample_product.team.tea_enabled = True
    sample_product.team.save()
    return sample_product


@pytest.fixture
def tea_enabled_component(sample_component):
    """Component with TEA enabled on its team."""
    sample_component.visibility = Component.Visibility.PUBLIC
    sample_component.save()
    sample_component.team.tea_enabled = True
    sample_component.team.save()
    return sample_component


@pytest.fixture
def tea_conformance_data(sample_sbom):
    """Complete TEA data hierarchy for conformance testing.

    Creates a public team with TEA enabled, a product with a release,
    a public component, and an SBOM artifact linked via ReleaseArtifact.
    Returns (team, product, release, component, sbom).
    """
    component = sample_sbom.component
    project = component.project
    product = project.product

    team = product.team
    team.tea_enabled = True
    team.is_public = True
    team.save()

    product.is_public = True
    product.save()

    component.visibility = Component.Visibility.PUBLIC
    component.save()

    release = Release.objects.create(product=product, name="v1.0.0-conformance")
    ReleaseArtifact.objects.create(release=release, sbom=sample_sbom)

    return team, product, release, component, sample_sbom
