"""Fixtures for the MCP server tests."""

from __future__ import annotations

import pytest
from asgiref.sync import SyncToAsync
from django.db import connections

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.access_tokens.utils import create_personal_access_token
from sbomify.apps.core.utils import number_to_random_token
from sbomify.apps.teams.models import Member, Workspace


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


@pytest.fixture(autouse=True)
def _close_executor_thread_connections():
    """Close the DB connection these tests leave on asgiref's shared executor thread.

    The tests drive the MCP app without a ThreadSensitiveContext, so their own
    ``sync_to_async`` calls run on the one process-wide executor thread, and a
    plain ``sync_to_async`` never closes the connection it opened. The next
    async test on that worker then reaches for it while pytest-django blocks
    database access, which failed the websocket tests in ``core``.
    """
    yield
    SyncToAsync.single_thread_executor.submit(connections.close_all).result()


def _make_team(name: str) -> Workspace:
    team = Workspace.objects.create(name=name)
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

    def _make(scopes: list[str] | None = None, team: Workspace | None = None) -> AccessToken:
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
    from sbomify.apps.teams.models import ContactEntity, ContactProfile

    _, bound, _ = mcp_owner
    # With an entity, as the API now requires of every saved profile: an update
    # that would leave a profile without one is refused and rolled back.
    profile = ContactProfile.objects.create(name="Bound Supplier", team=bound)
    ContactEntity.objects.create(profile=profile, name="Bound Supplier Ltd", email="supplier@example.com", is_supplier=True)
    return profile
