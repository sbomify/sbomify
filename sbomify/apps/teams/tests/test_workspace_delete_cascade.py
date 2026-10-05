"""Deleting a workspace must not leave anything of it behind.

Seventeen tables point at Team directly, and far more hang below them. The
check that matters is not that the seventeen go, which the field definitions
already say, but that nothing survives anywhere in the graph: an orphaned SBOM
or advisory row keeps a deleted workspace's data alive and readable by id.

Rather than name the tables and go stale the next time one is added, this walks
the reverse relations from Team and asserts every reachable model is empty. A
new child table is covered the day it is created.

Scope, stated plainly: the walk reaches 62 models and the fixture populates ten
of them, so the behavioural test proves those ten leave nothing behind and would
catch an orphan anywhere in the other 52. Every one of the seventeen tables that
point at Team directly is covered structurally by the second test instead, which
is the check that fails when someone adds a child with SET_NULL.
"""

from __future__ import annotations

import pytest

from sbomify.apps.access_tokens.models import AccessToken
from sbomify.apps.core.models import Component, Product
from sbomify.apps.security_advisories.models import SecurityAdvisory
from sbomify.apps.teams.models import ContactProfile, Invitation, Member, Supplier, Team


def _models_reachable_from_team() -> list[type]:
    """Every model reachable from Team by following reverse relations."""
    seen: set[type] = set()
    frontier = [Team]
    while frontier:
        nxt = []
        for model in frontier:
            if model in seen:
                continue
            seen.add(model)
            for field in model._meta.get_fields():
                if field.auto_created and not field.concrete:
                    nxt.append(field.related_model)
        frontier = nxt
    seen.discard(Team)
    return sorted(seen, key=lambda m: m._meta.label)


@pytest.fixture
def populated_workspace(db, django_user_model):
    """A workspace with a row in the child tables that are cheap to make."""
    user = django_user_model.objects.create_user(username="cascade", email="cascade@test.com", password="password")
    team = Team.objects.create(name="Doomed Workspace")

    Member.objects.create(user=user, team=team, role="owner", is_default_team=True)
    Invitation.objects.create(team=team, email="invitee@test.com", role="member")
    ContactProfile.objects.create(team=team, name="Security")
    Supplier.objects.create(team=team, name="Acme Supplies")
    AccessToken.objects.create(user=user, team=team, encoded_token="tok-cascade", description="cascade")

    product = Product.objects.create(name="Doomed Product", team=team)
    component = Component.objects.create(name="Doomed Component", team=team)
    product.components.add(component)

    SecurityAdvisory.objects.create(team=team, title="Doomed Advisory")

    return team


@pytest.mark.django_db
def test_deleting_a_workspace_leaves_nothing_reachable_behind(populated_workspace):
    """The database holds this workspace and nothing else, so after the delete
    every table reachable from Team must be empty. Anything left is an orphan."""
    reachable = _models_reachable_from_team()
    before = {m._meta.label: m._default_manager.count() for m in reachable}
    assert sum(before.values()) > 0, "the fixture populated nothing, so this proves nothing"

    populated_workspace.delete()

    survivors = {
        label: count for label, count in ((m._meta.label, m._default_manager.count()) for m in reachable) if count
    }
    assert survivors == {}, f"rows outlived their workspace: {survivors}"


@pytest.mark.django_db
def test_every_table_pointing_at_a_workspace_cascades(db):
    """A child added with SET_NULL or PROTECT would strand or block a delete."""
    offenders = []
    for field in Team._meta.get_fields():
        if not (field.auto_created and not field.concrete):
            continue
        remote = getattr(field.field, "remote_field", None)
        behaviour = getattr(remote, "on_delete", None)
        if getattr(behaviour, "__name__", "") != "CASCADE":
            offenders.append(f"{field.related_model._meta.label}.{field.field.name}")

    assert offenders == [], f"these point at Team without cascading: {offenders}"


@pytest.mark.django_db
def test_deleting_a_workspace_spares_its_neighbours(populated_workspace, django_user_model):
    """A cascade that reached across workspaces would be worse than an orphan."""
    other_user = django_user_model.objects.create_user(
        username="bystander", email="bystander@test.com", password="password"
    )
    other = Team.objects.create(name="Innocent Workspace")
    Member.objects.create(user=other_user, team=other, role="owner", is_default_team=True)
    kept_product = Product.objects.create(name="Kept Product", team=other)
    kept_advisory = SecurityAdvisory.objects.create(team=other, title="Kept Advisory")

    populated_workspace.delete()

    assert Team.objects.filter(pk=other.pk).exists()
    assert Product.objects.filter(pk=kept_product.pk).exists()
    assert SecurityAdvisory.objects.filter(pk=kept_advisory.pk).exists()
    assert Member.objects.filter(team=other).count() == 1
