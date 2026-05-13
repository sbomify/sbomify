"""Cross-tenant rejection tests for the Product↔Component link.

The PR that removed the Project layer introduced a `ProductComponent` M2M with
three independent layers of cross-tenant defense:

1. The ``m2m_changed`` ``pre_add`` signal at
   ``sbomify/apps/core/signals.py:reject_cross_tenant_product_component_links``,
   which catches forward (``component.products.add(product)``) and reverse
   (``product.components.add(component)``) calls — including ``.set()``.
2. The through-model ``ProductComponent.clean()`` + ``save()`` override at
   ``sbomify/apps/sboms/models.py``, which catches direct
   ``ProductComponent.objects.create(product=p, component=c)`` calls that
   bypass the M2M (since the signal doesn't fire for direct through-model
   instantiation).
3. The backfill migration's pre-filter ``WHERE p.team_id = c.team_id``
   (covered by the migration test, not here — see ``test_migration_backfill``).

These tests assert the first two layers reject cross-tenant pairings, and
that ``bulk_create`` *does* skip both guards (which is the documented
escape-hatch used only by the backfill migration — any future caller must
pre-filter explicitly).
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from sbomify.apps.sboms.models import Component, Product, ProductComponent
from sbomify.apps.teams.models import Team


@pytest.fixture
def two_teams(db) -> tuple[Team, Team]:
    return Team.objects.create(name="Team A"), Team.objects.create(name="Team B")


@pytest.fixture
def cross_tenant_pair(two_teams: tuple[Team, Team]) -> tuple[Product, Component]:
    team_a, team_b = two_teams
    product = Product.objects.create(name="A's Product", team=team_a)
    component = Component.objects.create(name="B's Component", team=team_b)
    return product, component


@pytest.fixture
def same_tenant_pair(two_teams: tuple[Team, Team]) -> tuple[Product, Component]:
    team_a, _ = two_teams
    product = Product.objects.create(name="A's Product", team=team_a)
    component = Component.objects.create(name="A's Component", team=team_a)
    return product, component


class TestSignalRejectsCrossTenantM2M:
    """Layer 1: ``m2m_changed`` ``pre_add`` receiver in core.signals."""

    def test_forward_add_rejects_cross_tenant(self, cross_tenant_pair):
        product, component = cross_tenant_pair
        with pytest.raises(ValidationError, match=r"Cross-tenant"):
            component.products.add(product)

    def test_reverse_add_rejects_cross_tenant(self, cross_tenant_pair):
        product, component = cross_tenant_pair
        with pytest.raises(ValidationError, match=r"Cross-tenant"):
            product.components.add(component)

    def test_reverse_set_rejects_cross_tenant(self, cross_tenant_pair):
        product, component = cross_tenant_pair
        with pytest.raises(ValidationError, match=r"Cross-tenant"):
            product.components.set([component])

    def test_forward_set_rejects_cross_tenant(self, cross_tenant_pair):
        """Symmetry test for ``component.products.set([cross_tenant_product])``.

        Both directions of the M2M (``.set()`` on either side) trigger the
        same ``m2m_changed pre_add`` receiver; we exercise both so a future
        refactor that mistakenly handles only the reverse case fails here.
        """
        product, component = cross_tenant_pair
        with pytest.raises(ValidationError, match=r"Cross-tenant"):
            component.products.set([product])

    def test_reverse_set_mixed_list_rejects(self, two_teams):
        """A ``.set()`` call with a list containing BOTH same-team and
        cross-tenant entries must reject the whole call (the signal iterates
        ``pk_set`` and raises on the first cross-tenant pk). Without this
        test, a future short-circuit on ``len(pk_set) == 1`` would silently
        allow the mixed case through.

        The raise leaves the test transaction in a broken state, so we only
        assert on the exception itself — Django rolls back the whole `.set()`
        atomic block, so no rows are committed regardless.
        """
        team_a, team_b = two_teams
        product = Product.objects.create(name="A's Product", team=team_a)
        same_team_c = Component.objects.create(name="A's Component", team=team_a)
        cross_tenant_c = Component.objects.create(name="B's Component", team=team_b)

        with pytest.raises(ValidationError, match=r"Cross-tenant"):
            product.components.set([same_team_c, cross_tenant_c])

    def test_forward_add_allows_same_tenant(self, same_tenant_pair):
        product, component = same_tenant_pair
        component.products.add(product)
        assert product.components.count() == 1

    def test_reverse_add_allows_same_tenant(self, same_tenant_pair):
        product, component = same_tenant_pair
        product.components.add(component)
        assert component.products.count() == 1


class TestThroughModelCleanRejectsCrossTenant:
    """Layer 2: ``ProductComponent.clean()`` + ``save()`` override."""

    def test_create_rejects_cross_tenant(self, cross_tenant_pair):
        product, component = cross_tenant_pair
        with pytest.raises(ValidationError):
            ProductComponent.objects.create(product=product, component=component)

    def test_create_allows_same_tenant(self, same_tenant_pair):
        product, component = same_tenant_pair
        link = ProductComponent.objects.create(product=product, component=component)
        assert link.pk is not None

    def test_full_clean_rejects_cross_tenant(self, cross_tenant_pair):
        """clean() is callable independently of save() (e.g., in admin forms)."""
        product, component = cross_tenant_pair
        link = ProductComponent(product=product, component=component)
        with pytest.raises(ValidationError):
            link.full_clean()


class TestComponentIsGlobalInvariants:
    """``Component.save()`` and ``.clean()`` centralise the two ``is_global``
    invariants that were previously duplicated across four call sites
    (``core/apis.py`` x2, ``core/views/__init__.py``, and
    ``core/views/component_scope.py``):

    1. Setting ``is_global=True`` on a component that has products attached
       MUST detach those products in the same save (the M2M cannot survive
       the scope flip — global means workspace-only).
    2. ``is_global=True`` is only valid for ``component_type=DOCUMENT``;
       BOM components must remain attached to at least one product.
    """

    def test_save_clears_products_when_promoted_to_global(self, two_teams):
        team_a, _ = two_teams
        product = Product.objects.create(name="P", team=team_a)
        component = Component.objects.create(
            name="C",
            team=team_a,
            component_type=Component.ComponentType.DOCUMENT,
        )
        component.products.add(product)
        assert component.products.count() == 1

        component.is_global = True
        component.save()

        component.refresh_from_db()
        assert component.is_global is True
        assert component.products.count() == 0, (
            "Component.save() must detach all products when is_global flips to True"
        )

    def test_save_does_not_touch_products_when_not_global(self, two_teams):
        team_a, _ = two_teams
        product = Product.objects.create(name="P", team=team_a)
        component = Component.objects.create(name="C", team=team_a)
        component.products.add(product)
        assert component.products.count() == 1

        component.name = "C renamed"
        component.save()

        component.refresh_from_db()
        assert component.products.count() == 1, "Non-global save must leave products alone"

    def test_save_does_not_reattach_on_global_to_product(self, two_teams):
        """Demoting a component from workspace-scope (is_global=True) back to
        product-scope (is_global=False) must NOT re-attach the products that
        were detached on promotion. The previous attachments are gone — the
        caller is responsible for re-attaching the component to whichever
        products it should now belong to.
        """
        team_a, _ = two_teams
        product = Product.objects.create(name="P", team=team_a)
        component = Component.objects.create(
            name="C",
            team=team_a,
            component_type=Component.ComponentType.DOCUMENT,
        )
        component.products.add(product)
        assert component.products.count() == 1

        # Promote to global — products detach.
        component.is_global = True
        component.save()
        component.refresh_from_db()
        assert component.products.count() == 0

        # Demote back to product-scope — products MUST STAY detached.
        component.is_global = False
        component.save()
        component.refresh_from_db()
        assert component.products.count() == 0, (
            "Demoting from is_global=True back to False must NOT re-attach products"
        )

    def test_queryset_update_bypasses_save_invariant(self, two_teams):
        """Foot-gun pin: ``Component.objects.filter(...).update(is_global=True)``
        bypasses ``Component.save()`` entirely, so the products-detach
        invariant does NOT fire. This is Django's documented behaviour for
        ``QuerySet.update``; the test exists so a future maintainer who
        adds a ``CheckConstraint`` or DB trigger to close this hole is
        flagged here intentionally.

        Any code path doing ``Component.objects.filter(...).update(is_global=True)``
        without explicitly calling ``component.products.clear()`` first is
        a bug. There are currently no such call sites in the codebase
        (verified by grep at the time this test was written).
        """
        team_a, _ = two_teams
        product = Product.objects.create(name="P", team=team_a)
        component = Component.objects.create(
            name="C",
            team=team_a,
            component_type=Component.ComponentType.DOCUMENT,
        )
        component.products.add(product)

        # Bypass save() via QuerySet.update
        Component.objects.filter(pk=component.pk).update(is_global=True)

        component.refresh_from_db()
        assert component.is_global is True
        # The invariant is NOT enforced by QuerySet.update — the M2M
        # still has the row. This pins the bypass so a future fix
        # (e.g., a pre_save signal, CheckConstraint, or DB trigger)
        # that closes the gap will be caught here for explicit review.
        assert component.products.count() == 1, (
            "QuerySet.update bypasses Component.save() invariant. "
            "If this assertion starts failing, a new enforcement mechanism "
            "has been added — update this test to assert the new contract."
        )

    def test_clean_rejects_global_on_bom_component(self, two_teams):
        team_a, _ = two_teams
        component = Component(
            name="C",
            team=team_a,
            component_type=Component.ComponentType.BOM,
            is_global=True,
        )
        with pytest.raises(ValidationError, match=r"document components"):
            component.full_clean()

    def test_clean_allows_global_on_document_component(self, two_teams):
        team_a, _ = two_teams
        component = Component(
            name="C",
            team=team_a,
            component_type=Component.ComponentType.DOCUMENT,
            is_global=True,
        )
        # full_clean() should not raise on is_global=True for DOCUMENT
        component.full_clean()


class TestBulkCreateEscapeHatch:
    """Bulk create deliberately bypasses both guards — the backfill migration
    relies on this and pre-filters cross-tenant pairs in SQL. Document the
    contract here so a future caller who reaches for ``bulk_create`` is
    forced to read the test that explains the constraint."""

    def test_bulk_create_does_not_validate(self, cross_tenant_pair):
        """``bulk_create`` skips ``save()`` and ``m2m_changed``. This is
        Django's documented behaviour and our backfill depends on it; the
        test pins the behaviour so a future override of ``save()`` that
        also blocks ``bulk_create`` (e.g., a DB-level CHECK constraint) is
        caught here intentionally."""
        product, component = cross_tenant_pair
        ProductComponent.objects.bulk_create(
            [ProductComponent(product=product, component=component)],
            ignore_conflicts=True,
        )
        # Confirms the cross-tenant row was inserted — proving the guard
        # is bypassed and that any caller using bulk_create *must* pre-filter.
        assert ProductComponent.objects.filter(
            product=product, component=component
        ).exists()
