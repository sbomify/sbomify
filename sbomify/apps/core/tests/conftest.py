# Re-export fixtures from other modules so pytest can auto-discover them
# without needing explicit imports in test files
from sbomify.apps.core.tests.fixtures import guest_user, sample_user
from sbomify.apps.core.tests.shared_fixtures import (
    authenticated_api_client,
    authenticated_web_client,
    get_api_headers,
    guest_api_client,
    setup_authenticated_client_session,
    team_with_business_plan,
    team_with_community_plan,
    team_with_enterprise_plan,
    team_with_multiple_members,
)

# Make fixtures available to pytest
__all__ = [
    "guest_user",
    "sample_user",
    "authenticated_api_client",
    "authenticated_web_client",
    "get_api_headers",
    "guest_api_client",
    "setup_authenticated_client_session",
    "team_with_business_plan",
    "team_with_community_plan",
    "team_with_enterprise_plan",
    "team_with_multiple_members",
]
