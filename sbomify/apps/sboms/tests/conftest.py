# Re-export fixtures from other modules so pytest can auto-discover them
# without needing explicit imports in test files
from sbomify.apps.core.tests.fixtures import sample_user
from sbomify.apps.teams.fixtures import sample_team, sample_team_with_owner_member

from .fixtures import (
    sample_access_token,
    sample_billing_plan,
    sample_component,
    sample_product,
    sample_sbom,
)

# Make fixtures available to pytest
__all__ = [
    "sample_user",
    "sample_team",
    "sample_team_with_owner_member",
    "sample_access_token",
    "sample_billing_plan",
    "sample_component",
    "sample_product",
    "sample_sbom",
]
