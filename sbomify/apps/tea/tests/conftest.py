import uuid

import pytest

from sbomify.apps.core.models import Component, Release, ReleaseArtifact
from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_billing_plan,
    sample_component,
    sample_product,
    sample_sbom,
)
from sbomify.apps.tea.models import TeaSubscription
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
    # sample_component fixture attaches the component to sample_product via
    # ProductComponent, so we can resolve the product directly off the M2M.
    product = component.products.first()
    assert product is not None, "sample_component fixture must attach the component to a product"

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


@pytest.fixture
def make_subscription():
    """Build a TEA subscription component in a workspace, as the import wizard leaves it."""

    def make(team, name="remote library", **fields):
        component = Component.objects.create(
            team=team,
            name=name,
            component_type=Component.ComponentType.TEA_SUBSCRIPTION,
            visibility=Component.Visibility.PUBLIC,
        )
        return TeaSubscription.objects.create(
            component=component,
            api_base_url="https://tea.example.com/tea/v1.0.0",
            spec_version="1.0.0",
            remote_component_uuid=str(uuid.uuid4()),
            remote_name=name,
            **fields,
        )

    return make


def pytest_collection_modifyitems(config, items):
    """``live_tea`` tests read the sbomify servers over the internet, so they run only when ``-m live_tea`` asks."""
    if "live_tea" in (config.getoption("markexpr") or ""):
        return
    skip = pytest.mark.skip(reason="Reads the sbomify TEA servers; run with -m live_tea")
    for item in items:
        if "live_tea" in item.keywords:
            item.add_marker(skip)
