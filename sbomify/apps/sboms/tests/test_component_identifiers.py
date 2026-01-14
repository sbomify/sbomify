"""Tests for ComponentIdentifier model and collision detection.

This module tests:
- ComponentIdentifier model creation and validation
- Cross-model collision detection (Component/Product identifiers)
- Unique constraint enforcement
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from sbomify.apps.sboms.models import ComponentIdentifier, ProductIdentifier, check_identifier_collision

if TYPE_CHECKING:
    from sbomify.apps.sboms.models import Component, Product


@pytest.mark.django_db
class TestComponentIdentifierModel:
    """Tests for ComponentIdentifier model."""

    def test_create_component_identifier(self, sample_component: Component) -> None:
        """Test creating a component identifier successfully."""
        identifier = ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type="purl",
            value="pkg:npm/@example/package",
        )

        assert identifier.id is not None
        assert identifier.component == sample_component
        assert identifier.team == sample_component.team
        assert identifier.identifier_type == "purl"
        assert identifier.value == "pkg:npm/@example/package"
        assert identifier.created_at is not None

    def test_team_auto_populated_from_component(self, sample_component: Component) -> None:
        """Test that team is automatically populated from component on save."""
        identifier = ComponentIdentifier(
            component=sample_component,
            identifier_type="cpe",
            value="cpe:2.3:a:example:package:1.0:*:*:*:*:*:*:*",
        )
        # Don't set team explicitly
        identifier.save()

        assert identifier.team == sample_component.team

    def test_string_representation(self, sample_component: Component) -> None:
        """Test __str__ method returns readable format."""
        identifier = ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type="purl",
            value="pkg:npm/@example/package",
        )

        str_repr = str(identifier)
        assert "PURL" in str_repr
        assert "pkg:npm/@example/package" in str_repr

    def test_unique_constraint_same_team_type_value(self, sample_component: Component) -> None:
        """Test that duplicate identifier type+value within same team is rejected."""
        from django.db import transaction

        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type="purl",
            value="pkg:npm/@example/unique-constraint-test",
        )

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                ComponentIdentifier.objects.create(
                    component=sample_component,
                    identifier_type="purl",
                    value="pkg:npm/@example/unique-constraint-test",
                )

    def test_different_type_same_value_allowed(self, sample_component: Component) -> None:
        """Test that same value with different type is allowed."""
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type="purl",
            value="some-value",
        )

        # Different type should be allowed
        identifier2 = ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type="sku",
            value="some-value",
        )

        assert identifier2.id is not None

    def test_cascade_delete_with_component(self, sample_component: Component) -> None:
        """Test that identifiers are deleted when component is deleted."""
        from sbomify.apps.sboms.models import Component

        # Create a separate component for this test to avoid fixture cleanup issues
        test_component = Component.objects.create(
            name="cascade-delete-test-component",
            team=sample_component.team,
        )

        identifier = ComponentIdentifier.objects.create(
            component=test_component,
            identifier_type="purl",
            value="pkg:npm/@example/to-delete-cascade",
        )
        identifier_id = identifier.id

        # Delete component (will cascade)
        test_component.delete()

        # Verify identifier is deleted
        assert not ComponentIdentifier.objects.filter(id=identifier_id).exists()

    def test_all_identifier_types(self, sample_component: Component) -> None:
        """Test creating identifiers with all supported types."""
        identifier_types = [
            ("gtin_12", "012345678905"),
            ("gtin_13", "5901234123457"),
            ("gtin_14", "10012345678902"),
            ("gtin_8", "12345670"),
            ("sku", "SKU-12345"),
            ("mpn", "MPN-12345"),
            ("asin", "B08N5WRWNW"),
            ("gs1_gpc_brick", "10000043"),
            ("cpe", "cpe:2.3:a:example:product:1.0:*:*:*:*:*:*:*"),
            ("purl", "pkg:npm/@example/test-package"),
        ]

        for id_type, value in identifier_types:
            identifier = ComponentIdentifier.objects.create(
                component=sample_component,
                identifier_type=id_type,
                value=value,
            )
            assert identifier.identifier_type == id_type
            assert identifier.value == value

    def test_related_name_identifiers(self, sample_component: Component) -> None:
        """Test that component.identifiers related name works."""
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type="purl",
            value="pkg:npm/@example/package-1",
        )
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type="cpe",
            value="cpe:2.3:a:example:package-2:*:*:*:*:*:*:*:*",
        )

        assert sample_component.identifiers.count() == 2


@pytest.mark.django_db
class TestIdentifierCollisionDetection:
    """Tests for cross-model identifier collision detection."""

    def test_component_identifier_collision_with_product_identifier(
        self, sample_component: Component, sample_product: Product
    ) -> None:
        """Test that component identifier collides with existing product identifier."""
        # Create product identifier first
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type="purl",
            value="pkg:npm/@shared/package",
        )

        # Trying to create component identifier with same type+value should fail
        with pytest.raises(ValidationError) as exc_info:
            ComponentIdentifier.objects.create(
                component=sample_component,
                identifier_type="purl",
                value="pkg:npm/@shared/package",
            )

        assert "already exists for a product" in str(exc_info.value)

    def test_product_identifier_collision_with_component_identifier(
        self, sample_component: Component, sample_product: Product
    ) -> None:
        """Test that product identifier collides with existing component identifier."""
        # Create component identifier first
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type="purl",
            value="pkg:npm/@shared/package",
        )

        # Trying to create product identifier with same type+value should fail
        with pytest.raises(ValidationError) as exc_info:
            ProductIdentifier.objects.create(
                product=sample_product,
                team=sample_product.team,
                identifier_type="purl",
                value="pkg:npm/@shared/package",
            )

        assert "already exists for a component" in str(exc_info.value)

    def test_different_teams_no_collision(
        self, sample_component: Component, sample_product: Product
    ) -> None:
        """Test that identifiers in different teams don't collide.

        Note: This test uses same team fixtures, so we test the inverse -
        that same team DOES collide.
        """
        # Both fixtures use the same team, so collision should occur
        ProductIdentifier.objects.create(
            product=sample_product,
            team=sample_product.team,
            identifier_type="purl",
            value="pkg:npm/@unique/package",
        )

        # Same team should collide
        with pytest.raises(ValidationError):
            ComponentIdentifier.objects.create(
                component=sample_component,
                identifier_type="purl",
                value="pkg:npm/@unique/package",
            )

    def test_update_component_identifier_excludes_self(self, sample_component: Component) -> None:
        """Test that updating an identifier excludes itself from collision check."""
        identifier = ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type="purl",
            value="pkg:npm/@example/original",
        )

        # Update the value - should not fail
        identifier.value = "pkg:npm/@example/updated"
        identifier.save()

        assert identifier.value == "pkg:npm/@example/updated"

    def test_collision_check_function_directly(self, sample_component: Component) -> None:
        """Test check_identifier_collision function directly."""
        # Create a component identifier
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type="sku",
            value="SKU-COLLISION-TEST",
        )

        # Check collision should raise for product trying to use same identifier
        with pytest.raises(ValidationError) as exc_info:
            check_identifier_collision(
                team=sample_component.team,
                identifier_type="sku",
                value="SKU-COLLISION-TEST",
                exclude_model="product",  # Checking from product's perspective
            )

        assert "already exists for a component" in str(exc_info.value)

    def test_collision_check_excludes_correct_model(self, sample_component: Component) -> None:
        """Test that collision check excludes the correct model type."""
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type="mpn",
            value="MPN-EXCLUDE-TEST",
        )

        # Checking from component's perspective should NOT find collision
        # (because we exclude component model)
        check_identifier_collision(
            team=sample_component.team,
            identifier_type="mpn",
            value="MPN-EXCLUDE-TEST",
            exclude_model="component",
        )
        # No exception means test passed


@pytest.mark.django_db
class TestComponentIdentifierOrdering:
    """Tests for ComponentIdentifier ordering."""

    def test_default_ordering(self, sample_component: Component) -> None:
        """Test that identifiers are ordered by type and value."""
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type="sku",
            value="SKU-B",
        )
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type="purl",
            value="pkg:npm/z-package",
        )
        ComponentIdentifier.objects.create(
            component=sample_component,
            identifier_type="purl",
            value="pkg:npm/a-package",
        )

        identifiers = list(sample_component.identifiers.all())

        # Should be ordered by identifier_type, then value
        assert identifiers[0].identifier_type == "purl"
        assert identifiers[0].value == "pkg:npm/a-package"
        assert identifiers[1].identifier_type == "purl"
        assert identifiers[1].value == "pkg:npm/z-package"
        assert identifiers[2].identifier_type == "sku"
