"""Fixtures for the MCP server tests."""

from __future__ import annotations

import pytest

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Member, Team


@pytest.fixture(autouse=True)
def _enforce_async_safety(monkeypatch):
    """Re-arm Django's SynchronousOnlyOperation guard for MCP tests.

    The suite sets ``DJANGO_ALLOW_ASYNC_UNSAFE=1`` globally for the Playwright
    e2e tests, which disables the very guard the MCP async contract rests on —
    an ORM call that escapes ``run_db`` onto the event loop must raise, here as
    in production. Django reads the variable per call, so removing it for this
    app's tests restores the invariant without touching e2e.
    """
    monkeypatch.delenv("DJANGO_ALLOW_ASYNC_UNSAFE", raising=False)


def _make_team(name: str) -> Team:
    team = Team.objects.create(name=name)
    team.key = number_to_random_token(team.pk)
    team.save()
    return team


@pytest.fixture
def mcp_owner(db, django_user_model):
    """An owner of two workspaces, so cross-workspace leakage is testable."""
    user = django_user_model.objects.create_user(
        username="mcpowner", email="mcpowner@example.com", password="pw"
    )
    bound = _make_team("MCP Bound WS")
    other = _make_team("MCP Other WS")
    Member.objects.create(user=user, team=bound, role="owner", is_default_team=True)
    Member.objects.create(user=user, team=other, role="owner", is_default_team=False)
    return user, bound, other


@pytest.fixture
def make_token(mcp_owner):
    """Build an AccessToken for the bound workspace with the given scopes."""
    user, bound, _ = mcp_owner

    def _make(scopes: list[str] | None = None, team: Team | None = None) -> AccessToken:
        return AccessToken.objects.create(
            user=user,
            encoded_token=create_personal_access_token(user),
            team=bound if team is None else team,
            scopes=scopes,
            description="MCP test token",
        )

    return _make


@pytest.fixture
def product_in_bound_workspace(mcp_owner):
    from sbomify.apps.core.models import Product

    _, bound, _ = mcp_owner
    return Product.objects.create(name="Bound Product", team=bound)


@pytest.fixture
def product_in_other_workspace(mcp_owner):
    from sbomify.apps.core.models import Product

    _, _, other = mcp_owner
    return Product.objects.create(name="Other Product", team=other)


@pytest.fixture
def component_in_bound_workspace(mcp_owner):
    from sbomify.apps.core.models import Component

    _, bound, _ = mcp_owner
    return Component.objects.create(name="Bound Component", team=bound)


@pytest.fixture
def component_in_other_workspace(mcp_owner):
    from sbomify.apps.core.models import Component

    _, _, other = mcp_owner
    return Component.objects.create(name="Other Component", team=other)


@pytest.fixture
def contact_profile_in_bound_workspace(mcp_owner):
    from sbomify.apps.teams.models import ContactProfile

    _, bound, _ = mcp_owner
    return ContactProfile.objects.create(name="Bound Supplier", team=bound)
