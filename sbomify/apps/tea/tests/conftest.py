import pytest

from sbomify.apps.core.tests.fixtures import sample_user  # noqa: F401
from sbomify.apps.teams.fixtures import sample_team  # noqa: F401

from sbomify.apps.sboms.tests.fixtures import (  # noqa: F401
    sample_billing_plan,
    sample_component,
    sample_product,
    sample_project,
    sample_sbom,
)

from sbomify.apps.core.models import Component


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
